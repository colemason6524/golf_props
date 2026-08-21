import csv
from pathlib import Path

from golf_props.cli import main
from golf_props.features.player_event import build_features
from golf_props.models.time_split_baseline import (
    CALIBRATION_COLUMNS,
    METRIC_COLUMNS,
    PREDICTION_COLUMNS,
    run_time_split_baseline,
)
from golf_props.normalization.bootstrap_results import normalize_file

FIXTURE = Path(__file__).parent / "fixtures" / "sample_pga_results.csv"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def prepare_features(tmp_path):
    processed_dir = tmp_path / "processed"
    features_path = tmp_path / "features" / "player_event_features.csv"
    normalize_file(FIXTURE, processed_dir)
    build_features(processed_dir, features_path)
    return features_path


def test_time_split_baseline_writes_reports(tmp_path):
    features_path = prepare_features(tmp_path)
    output_dir = tmp_path / "reports" / "time_split_baseline"

    result = run_time_split_baseline(features_path, output_dir)

    assert (output_dir / "metrics.csv").exists()
    assert (output_dir / "predictions.csv").exists()
    assert (output_dir / "calibration.csv").exists()
    assert (output_dir / "report.txt").exists()
    assert result["metrics"]
    assert result["predictions"]
    assert result["calibration"]


def test_time_split_baseline_outputs_expected_columns_and_counts(tmp_path):
    features_path = prepare_features(tmp_path)
    output_dir = tmp_path / "reports" / "time_split_baseline"

    run_time_split_baseline(features_path, output_dir)

    metrics = read_csv(output_dir / "metrics.csv")
    predictions = read_csv(output_dir / "predictions.csv")
    calibration = read_csv(output_dir / "calibration.csv")

    assert list(metrics[0].keys()) == METRIC_COLUMNS
    assert list(predictions[0].keys()) == PREDICTION_COLUMNS
    assert list(calibration[0].keys()) == CALIBRATION_COLUMNS

    assert len(metrics) == 4
    assert len(predictions) == 9
    assert {row["target"] for row in metrics} == {
        "target_make_cut",
        "target_top20",
        "target_top10",
        "target_top5",
    }


def test_make_cut_fixture_split_uses_prior_event_base_rate(tmp_path):
    features_path = prepare_features(tmp_path)
    output_dir = tmp_path / "reports" / "time_split_baseline"

    run_time_split_baseline(features_path, output_dir)

    metrics = read_csv(output_dir / "metrics.csv")
    predictions = read_csv(output_dir / "predictions.csv")
    make_cut_metric = next(row for row in metrics if row["target"] == "target_make_cut")
    make_cut_predictions = [row for row in predictions if row["target"] == "target_make_cut"]

    assert make_cut_metric["train_rows"] == "3"
    assert make_cut_metric["test_rows"] == "3"
    assert float(make_cut_metric["train_positive_rate"]) == 0.666667
    assert float(make_cut_metric["actual_rate"]) == 0.666667
    assert {float(row["base_rate_prob"]) for row in make_cut_predictions} == {0.666667}
    assert {row["model_type"] for row in make_cut_predictions} == {"base_rate"}


def test_cli_time_split_baseline(tmp_path):
    features_path = prepare_features(tmp_path)
    output_dir = tmp_path / "reports" / "time_split_baseline"

    exit_code = main(
        [
            "time-split-baseline",
            "--features",
            str(features_path),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    assert (output_dir / "metrics.csv").exists()


def test_player_rolling_model_outputs_readable_predictions(tmp_path):
    features_path = prepare_features(tmp_path)
    output_dir = tmp_path / "reports" / "player_rolling_baseline"

    run_time_split_baseline(
        features_path,
        output_dir,
        min_prior_starts=1,
        model="player_rolling",
    )

    predictions = read_csv(output_dir / "predictions.csv")
    make_cut_predictions = [row for row in predictions if row["target"] == "target_make_cut"]

    assert make_cut_predictions
    assert {row["model_type"] for row in make_cut_predictions} == {"player_rolling"}
    assert all(row["event_name"] for row in make_cut_predictions)
    assert all(row["player_name"] for row in make_cut_predictions)
    assert all(row["course_name"] for row in make_cut_predictions)
    assert any(row["player_rolling_prob"] != row["base_rate_prob"] for row in make_cut_predictions)
