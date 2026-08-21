import csv
from pathlib import Path

from golf_props.backtest.event_rankings import build_event_rankings
from golf_props.backtest.value_report import VALUE_COLUMNS, build_value_report
from golf_props.cli import main
from golf_props.features.player_event import build_features
from golf_props.models.time_split_baseline import run_time_split_baseline
from golf_props.normalization.bootstrap_results import normalize_file as normalize_results
from golf_props.normalization.manual_odds import normalize_file as normalize_odds

RESULTS_FIXTURE = Path(__file__).parent / "fixtures" / "sample_pga_results.csv"
ODDS_FIXTURE = Path(__file__).parent / "fixtures" / "sample_manual_odds.csv"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def prepare_rankings_and_odds(tmp_path):
    processed_dir = tmp_path / "processed"
    features_path = tmp_path / "features" / "player_event_features.csv"
    baseline_dir = tmp_path / "reports" / "player_rolling"
    rankings_dir = tmp_path / "reports" / "event_rankings"
    odds_path = tmp_path / "processed_odds" / "odds_snapshots.csv"

    normalize_results(RESULTS_FIXTURE, processed_dir)
    build_features(processed_dir, features_path)
    run_time_split_baseline(
        features_path,
        baseline_dir,
        min_prior_starts=1,
        model="player_rolling",
    )
    build_event_rankings(baseline_dir / "predictions.csv", rankings_dir)
    normalize_odds(ODDS_FIXTURE, odds_path)
    return rankings_dir / "event_rankings.csv", odds_path


def test_value_report_joins_rankings_to_odds(tmp_path):
    rankings, odds = prepare_rankings_and_odds(tmp_path)
    output_dir = tmp_path / "reports" / "value"

    result = build_value_report(rankings, odds, output_dir)
    rows = read_csv(output_dir / "value_report.csv")
    report = (output_dir / "report.md").read_text(encoding="utf-8")

    assert (output_dir / "value_report.csv").exists()
    assert (output_dir / "report.md").exists()
    assert result["value_rows"]
    assert list(rows[0].keys()) == VALUE_COLUMNS
    assert {row["player_name"] for row in rows} == {
        "Scottie Scheffler",
        "Rory McIlroy",
        "Jordan Spieth",
    }
    assert all(row["edge"] for row in rows)
    assert all(row["value_tier"] for row in rows)
    assert all(row["confidence_note"] for row in rows)
    assert "# Value Report" in report
    assert "## Placement Value" in report
    assert "## Market Favored / No Edge" in report
    assert "Scottie Scheffler" in report


def test_cli_value_report(tmp_path):
    rankings, odds = prepare_rankings_and_odds(tmp_path)
    output_dir = tmp_path / "reports" / "value"

    exit_code = main(
        [
            "value-report",
            "--rankings",
            str(rankings),
            "--odds",
            str(odds),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    assert (output_dir / "value_report.csv").exists()
