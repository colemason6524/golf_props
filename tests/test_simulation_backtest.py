import csv
from pathlib import Path

from golf_props.backtest.simulation_backtest import (
    CALIBRATION_COLUMNS,
    METRIC_COLUMNS,
    PREDICTION_COLUMNS,
    run_simulation_backtest,
)
from golf_props.cli import main
from golf_props.features.round_performance import build_round_performance
from golf_props.normalization.bootstrap_results import normalize_file

FIXTURE = Path(__file__).parent / "fixtures" / "sample_pga_results.csv"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def prepare_inputs(tmp_path):
    processed = tmp_path / "processed"
    round_performance = tmp_path / "round_performance.csv"
    normalize_file(FIXTURE, processed)
    build_round_performance(processed, round_performance)
    return processed, round_performance


def test_simulation_backtest_walks_forward_and_writes_metrics(tmp_path):
    processed, round_performance = prepare_inputs(tmp_path)
    output_dir = tmp_path / "backtest"

    result = run_simulation_backtest(
        processed,
        round_performance,
        output_dir,
        max_events=1,
        simulations=300,
        seed=11,
        cut_size=2,
        prior_rounds=4,
    )
    predictions = read_csv(output_dir / "predictions.csv")
    metrics = read_csv(output_dir / "metrics.csv")
    calibration = read_csv(output_dir / "calibration.csv")

    assert len(result["event_summaries"]) == 1
    assert result["event_summaries"][0]["event_name"] == "Masters Tournament"
    assert list(predictions[0]) == PREDICTION_COLUMNS
    assert list(metrics[0]) == METRIC_COLUMNS
    assert list(calibration[0]) == CALIBRATION_COLUMNS
    assert {row["target"] for row in metrics} == {
        "make_cut",
        "top20",
        "top10",
        "top5",
        "winner",
    }
    assert all(row["event_name"] == "Masters Tournament" for row in predictions)
    assert (output_dir / "report.md").exists()


def test_cli_simulation_backtest(tmp_path):
    processed, round_performance = prepare_inputs(tmp_path)
    output_dir = tmp_path / "backtest"

    exit_code = main(
        [
            "simulation-backtest",
            "--canonical-dir",
            str(processed),
            "--round-performance",
            str(round_performance),
            "--output-dir",
            str(output_dir),
            "--max-events",
            "1",
            "--simulations",
            "200",
            "--seed",
            "11",
            "--cut-size",
            "2",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "predictions.csv").exists()
    assert (output_dir / "metrics.csv").exists()
    assert (output_dir / "report.md").exists()
