import csv
import json
from pathlib import Path

from golf_props.backtest.course_challenger_validation import (
    FOLD_COLUMNS,
    PAIRED_METRIC_COLUMNS,
    paired_metrics,
    run_course_challenger_validation,
)
from golf_props.backtest.rolling_simulation_validation import RollingFold
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


def fixture_fold():
    return RollingFold(
        "sample",
        "2025-03-13",
        "2025-03-13",
        "2025-04-10",
        "2025-04-10",
    )


def test_paired_metrics_measure_challenger_against_incumbent():
    rows = [
        {
            "event_id": "event_1",
            "target": "make_cut",
            "actual": 0,
            "incumbent_prob": 0.5,
            "challenger_prob": 0.2,
        },
        {
            "event_id": "event_1",
            "target": "make_cut",
            "actual": 1,
            "incumbent_prob": 0.5,
            "challenger_prob": 0.8,
        },
    ]

    metrics = paired_metrics(rows)

    assert list(metrics[0]) == PAIRED_METRIC_COLUMNS
    assert metrics[0]["incumbent_brier"] == 0.25
    assert metrics[0]["challenger_brier"] == 0.04
    assert metrics[0]["brier_improvement"] == 0.21


def test_course_challenger_writes_paired_artifacts(tmp_path):
    processed, round_performance = prepare_inputs(tmp_path)
    output_dir = tmp_path / "challenger"

    result = run_course_challenger_validation(
        processed,
        round_performance,
        output_dir,
        [fixture_fold()],
        [180],
        [4],
        [4],
        [0, 1],
        [4],
        "2025-03-13",
        "2025-03-13",
        selection_simulations=50,
        evaluation_simulations=75,
        bootstrap_samples=100,
        calibration_bins=2,
        seed=41,
        cut_size=2,
    )
    folds = read_csv(output_dir / "folds.csv")
    manifest = json.loads((output_dir / "challenger_manifest.json").read_text())

    assert list(folds[0]) == FOLD_COLUMNS
    assert result["folds"][0]["course_adjustment_weight"] == 0
    assert all(row["brier_improvement"] == 0 for row in result["paired_metrics"])
    assert manifest["incumbent_status"] == "unchanged"
    assert manifest["status"].startswith("research_challenger")
    assert (output_dir / "paired_predictions.csv").exists()
    assert (output_dir / "paired_event_bootstrap.csv").exists()
    assert "incumbent remains" in (output_dir / "report.md").read_text()


def test_cli_course_challenger_validation(tmp_path):
    processed, round_performance = prepare_inputs(tmp_path)
    output_dir = tmp_path / "challenger"

    exit_code = main(
        [
            "course-challenger-validation",
            "--canonical-dir",
            str(processed),
            "--round-performance",
            str(round_performance),
            "--output-dir",
            str(output_dir),
            "--fold",
            "sample|2025-03-13|2025-03-13|2025-04-10|2025-04-10",
            "--half-life-grid",
            "180",
            "--prior-rounds-grid",
            "4",
            "--variance-prior-rounds-grid",
            "4",
            "--course-weight-grid",
            "0",
            "--course-prior-rounds-grid",
            "4",
            "--freeze-date-from",
            "2025-03-13",
            "--freeze-date-to",
            "2025-03-13",
            "--selection-simulations",
            "30",
            "--evaluation-simulations",
            "30",
            "--bootstrap-samples",
            "50",
            "--calibration-bins",
            "2",
            "--cut-size",
            "2",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "report.md").exists()
    assert (output_dir / "challenger_manifest.json").exists()
