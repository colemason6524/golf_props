import csv
import json
from pathlib import Path

import pytest

from golf_props.backtest.rolling_simulation_validation import (
    BOOTSTRAP_COLUMNS,
    CALIBRATION_COLUMNS,
    FOLD_COLUMNS,
    RollingFold,
    RollingValidationError,
    event_block_bootstrap,
    parse_fold,
    quantile_calibration,
    run_rolling_simulation_validation,
    validate_folds,
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


def fixture_fold():
    return RollingFold(
        "sample",
        "2025-03-13",
        "2025-03-13",
        "2025-04-10",
        "2025-04-10",
    )


def test_fold_validation_rejects_overlapping_evaluation_windows():
    with pytest.raises(RollingValidationError, match="overlap"):
        validate_folds(
            [
                RollingFold("a", "2022-01-01", "2022-12-31", "2023-01-01", "2023-12-31"),
                RollingFold("b", "2022-01-01", "2022-12-31", "2023-06-01", "2024-05-31"),
            ]
        )


def test_parse_fold_requires_five_parts():
    assert parse_fold("f1|2021-01-01|2021-12-31|2022-01-01|2022-12-31").fold_id == "f1"
    with pytest.raises(Exception, match="fold must be"):
        parse_fold("bad|2021-01-01")


def synthetic_predictions():
    rows = []
    for fold_id, event_id, probabilities, outcomes in [
        ("f1", "event_1", [0.2, 0.8], [0, 1]),
        ("f1", "event_2", [0.1, 0.9], [1, 0]),
        ("f2", "event_3", [0.1, 0.9], [0, 1]),
    ]:
        for index, (probability, actual) in enumerate(zip(probabilities, outcomes)):
            rows.append(
                {
                    "fold_id": fold_id,
                    "event_id": event_id,
                    "target": "make_cut",
                    "player_id": f"{event_id}_{index}",
                    "actual": actual,
                    "model_prob": probability,
                    "baseline_prob": 0.5,
                }
            )
    return rows


def test_event_bootstrap_is_reproducible_and_uses_event_units():
    first = event_block_bootstrap(synthetic_predictions(), samples=500, seed=23)
    second = event_block_bootstrap(synthetic_predictions(), samples=500, seed=23)

    assert first == second
    assert list(first[0]) == BOOTSTRAP_COLUMNS
    assert first[0]["events"] == 3
    assert first[0]["rows"] == 6
    assert first[0]["ci_lower_95"] <= first[0]["ci_upper_95"]
    assert first[0]["positive_fold_rate"] == 0.5


def test_quantile_calibration_writes_equal_frequency_buckets():
    rows = synthetic_predictions()
    buckets, summaries = quantile_calibration(rows, bin_count=3)

    assert len(buckets) == 3
    assert list(buckets[0]) == CALIBRATION_COLUMNS
    assert sum(row["rows"] for row in buckets) == 6
    assert summaries[0]["target"] == "make_cut"
    assert summaries[0]["calibration_intercept"] != ""
    assert summaries[0]["calibration_slope"] != ""


def test_rolling_validation_writes_manifest_and_outputs(tmp_path):
    processed, round_performance = prepare_inputs(tmp_path)
    output_dir = tmp_path / "rolling"

    result = run_rolling_simulation_validation(
        processed,
        round_performance,
        output_dir,
        [fixture_fold()],
        [180],
        [4],
        [4],
        "2025-03-13",
        "2025-03-13",
        selection_simulations=50,
        evaluation_simulations=75,
        bootstrap_samples=100,
        calibration_bins=2,
        seed=31,
        cut_size=2,
    )
    folds = read_csv(output_dir / "folds.csv")
    manifest = json.loads((output_dir / "frozen_model_manifest.json").read_text())

    assert list(folds[0]) == FOLD_COLUMNS
    assert len(result["folds"]) == 1
    assert manifest["status"] == "frozen_awaiting_future_evaluation"
    assert manifest["frozen_model"]["source_data_through"] == "2025-03-16"
    assert (
        manifest["frozen_model"]["prospective_holdout_after"]
        >= manifest["frozen_model"]["source_data_through"]
    )
    assert manifest["frozen_model"]["next_evaluation_rule"].startswith(
        "event_date_start"
    )
    assert (output_dir / "out_of_sample_predictions.csv").exists()
    assert (output_dir / "event_bootstrap.csv").exists()
    assert (output_dir / "calibration_summary.csv").exists()
    assert "not evidence of a betting edge" in (output_dir / "report.md").read_text()


def test_cli_rolling_simulation_validation(tmp_path):
    processed, round_performance = prepare_inputs(tmp_path)
    output_dir = tmp_path / "rolling"

    exit_code = main(
        [
            "rolling-simulation-validation",
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
    assert (output_dir / "frozen_model_manifest.json").exists()
