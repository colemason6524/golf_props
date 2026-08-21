import csv
from pathlib import Path

from golf_props.backtest.event_rankings import RANKING_COLUMNS, build_event_rankings
from golf_props.cli import main
from golf_props.features.player_event import build_features
from golf_props.models.time_split_baseline import run_time_split_baseline
from golf_props.normalization.bootstrap_results import normalize_file

FIXTURE = Path(__file__).parent / "fixtures" / "sample_pga_results.csv"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def prepare_predictions(tmp_path):
    processed_dir = tmp_path / "processed"
    features_path = tmp_path / "features" / "player_event_features.csv"
    baseline_dir = tmp_path / "reports" / "player_rolling"
    normalize_file(FIXTURE, processed_dir)
    build_features(processed_dir, features_path)
    run_time_split_baseline(
        features_path,
        baseline_dir,
        min_prior_starts=1,
        model="player_rolling",
    )
    return baseline_dir / "predictions.csv"


def test_event_rankings_write_csv_and_markdown(tmp_path):
    predictions = prepare_predictions(tmp_path)
    output_dir = tmp_path / "reports" / "event_rankings"

    result = build_event_rankings(predictions, output_dir, max_events=5, top_n=5)

    assert (output_dir / "event_rankings.csv").exists()
    assert (output_dir / "report.md").exists()
    assert result["rankings"]


def test_event_rankings_pivot_targets_and_assign_ranks(tmp_path):
    predictions = prepare_predictions(tmp_path)
    output_dir = tmp_path / "reports" / "event_rankings"
    build_event_rankings(predictions, output_dir, max_events=5, top_n=5)

    rows = read_csv(output_dir / "event_rankings.csv")
    report = (output_dir / "report.md").read_text(encoding="utf-8")

    assert list(rows[0].keys()) == RANKING_COLUMNS
    assert len(rows) == 3
    assert all(row["event_name"] == "Masters Tournament" for row in rows)
    assert all(row["player_name"] for row in rows)
    assert all(row["course_name"] for row in rows)
    assert all(row["make_cut_prob"] for row in rows)
    assert all(row["make_cut_rank"] for row in rows)
    assert "## 2025-04-10 - Masters Tournament" in report
    assert "### Top 20" in report
    assert "| Rank | Player | Prob | Actual |" in report


def test_cli_event_rankings(tmp_path):
    predictions = prepare_predictions(tmp_path)
    output_dir = tmp_path / "reports" / "event_rankings"

    exit_code = main(
        [
            "event-rankings",
            "--predictions",
            str(predictions),
            "--output-dir",
            str(output_dir),
            "--max-events",
            "5",
            "--top-n",
            "5",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "event_rankings.csv").exists()
