import csv
from pathlib import Path

from golf_props.cli import main
from golf_props.features.round_performance import (
    ROUND_PERFORMANCE_COLUMNS,
    build_round_performance,
)
from golf_props.normalization.bootstrap_results import normalize_file

FIXTURE = Path(__file__).parent / "fixtures" / "sample_pga_results.csv"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def prepare_results(tmp_path):
    processed = tmp_path / "processed"
    normalize_file(FIXTURE, processed)
    return processed


def test_round_performance_centers_each_event_round(tmp_path):
    processed = prepare_results(tmp_path)
    output = tmp_path / "round_performance.csv"

    result = build_round_performance(processed, output)
    rows = read_csv(output)
    players_round_one = [
        row
        for row in rows
        if row["event_name"] == "THE PLAYERS Championship"
        and row["round_number"] == "1"
    ]
    scottie = next(
        row for row in players_round_one if row["player_name"] == "Scottie Scheffler"
    )

    assert list(rows[0]) == ROUND_PERFORMANCE_COLUMNS
    assert len(rows) == 19
    assert result["summary"]["event_round_groups"] == 8
    assert (
        abs(sum(float(row["relative_to_field"]) for row in players_round_one))
        <= 0.000001
    )
    assert float(scottie["field_round_score_avg"]) == 69.333333
    assert float(scottie["relative_to_field"]) == 1.333333


def test_round_performance_excludes_implausible_partial_scores(tmp_path):
    processed = prepare_results(tmp_path)
    round_scores = processed / "round_scores.csv"
    rows = read_csv(round_scores)
    rows[0]["score"] = "22"
    with round_scores.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    output = tmp_path / "round_performance.csv"

    result = build_round_performance(processed, output)
    written = read_csv(output)

    assert len(written) == 18
    assert result["summary"]["out_of_range_score_rows"] == 1
    assert min(int(row["score"]) for row in written) >= 58


def test_cli_build_round_performance(tmp_path):
    processed = prepare_results(tmp_path)
    output = tmp_path / "round_performance.csv"
    report = tmp_path / "round_performance.report.md"

    exit_code = main(
        [
            "build-round-performance",
            "--input-dir",
            str(processed),
            "--output",
            str(output),
            "--report-output",
            str(report),
        ]
    )

    assert exit_code == 0
    assert output.exists()
    assert report.exists()
