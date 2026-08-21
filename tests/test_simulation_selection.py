import csv
import json
from pathlib import Path

import pytest

from golf_props.backtest.simulation_selection import (
    SELECTION_COLUMNS,
    SimulationSelectionError,
    run_simulation_model_selection,
    validate_windows,
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


def selection_args(processed, round_performance, output_dir):
    return {
        "canonical_dir": processed,
        "round_performance_path": round_performance,
        "output_dir": output_dir,
        "validation_date_from": "2025-03-13",
        "validation_date_to": "2025-03-13",
        "test_date_from": "2025-04-10",
        "test_date_to": "2025-04-10",
        "half_life_grid": [90, 180],
        "prior_rounds_grid": [2, 4],
        "variance_prior_rounds_grid": [4],
        "validation_simulations": 100,
        "test_simulations": 150,
        "seed": 17,
        "cut_size": 2,
    }


def test_selection_uses_disjoint_validation_and_test_windows(tmp_path):
    processed, round_performance = prepare_inputs(tmp_path)
    output_dir = tmp_path / "selection"

    result = run_simulation_model_selection(
        **selection_args(processed, round_performance, output_dir)
    )
    rows = read_csv(output_dir / "selection.csv")
    metadata = json.loads((output_dir / "selected_parameters.json").read_text())

    assert len(rows) == 4
    assert list(rows[0]) == SELECTION_COLUMNS
    assert sum(row["selected"] == "True" for row in rows) == 1
    assert {row["event_name"] for row in result["validation"]["predictions"]} == {
        "THE PLAYERS Championship"
    }
    assert {row["event_name"] for row in result["test"]["predictions"]} == {
        "Masters Tournament"
    }
    assert metadata["objective"] == "mean_normalized_brier_improvement"
    assert (output_dir / "selected_validation" / "metrics.csv").exists()
    assert (output_dir / "untouched_test" / "metrics.csv").exists()
    assert "not evidence of a betting edge" in (output_dir / "report.md").read_text()


def test_selection_is_reproducible_for_same_seed(tmp_path):
    processed, round_performance = prepare_inputs(tmp_path)

    first = run_simulation_model_selection(
        **selection_args(processed, round_performance, tmp_path / "first")
    )
    second = run_simulation_model_selection(
        **selection_args(processed, round_performance, tmp_path / "second")
    )

    assert first["selection_rows"] == second["selection_rows"]
    assert first["test"]["metrics"] == second["test"]["metrics"]


def test_selection_rejects_overlapping_windows():
    with pytest.raises(SimulationSelectionError, match="strictly before"):
        validate_windows("2025-01-01", "2025-04-10", "2025-04-10", "2025-12-31")


def test_cli_simulation_model_selection(tmp_path):
    processed, round_performance = prepare_inputs(tmp_path)
    output_dir = tmp_path / "selection"

    exit_code = main(
        [
            "simulation-model-selection",
            "--canonical-dir",
            str(processed),
            "--round-performance",
            str(round_performance),
            "--output-dir",
            str(output_dir),
            "--validation-date-from",
            "2025-03-13",
            "--validation-date-to",
            "2025-03-13",
            "--test-date-from",
            "2025-04-10",
            "--test-date-to",
            "2025-04-10",
            "--half-life-grid",
            "180",
            "--prior-rounds-grid",
            "4",
            "--variance-prior-rounds-grid",
            "4",
            "--validation-simulations",
            "50",
            "--test-simulations",
            "50",
            "--cut-size",
            "2",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "selection.csv").exists()
    assert (output_dir / "report.md").exists()
