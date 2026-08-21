"""Rolling-origin simulator validation with event-level uncertainty estimates."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from itertools import product
from pathlib import Path
from typing import Optional

import numpy as np

from golf_props.backtest.simulation_backtest import (
    METRIC_COLUMNS,
    PREDICTION_COLUMNS,
    SimulationBacktestInputs,
    evaluate_simulation_backtest,
    metric_rows,
    prepare_backtest_inputs,
    write_csv,
)
from golf_props.backtest.simulation_selection import (
    SELECTION_TARGETS,
    comma_separated_floats,
    selection_row,
    validated_grid,
)

ROLLING_PREDICTION_COLUMNS = [
    "fold_id",
    "half_life_days",
    "prior_rounds",
    "variance_prior_rounds",
    *PREDICTION_COLUMNS,
]

FOLD_COLUMNS = [
    "fold_id",
    "selection_date_from",
    "selection_date_to",
    "evaluation_date_from",
    "evaluation_date_to",
    "half_life_days",
    "prior_rounds",
    "variance_prior_rounds",
    "selection_mean_brier_skill",
    "selection_events",
    "evaluation_events",
]

FOLD_METRIC_COLUMNS = ["fold_id", *METRIC_COLUMNS]

BOOTSTRAP_COLUMNS = [
    "target",
    "events",
    "rows",
    "mean_event_brier_improvement",
    "ci_lower_95",
    "ci_upper_95",
    "bootstrap_probability_positive",
    "positive_event_rate",
    "positive_fold_rate",
    "worst_fold_brier_improvement",
    "best_fold_brier_improvement",
]

CALIBRATION_COLUMNS = [
    "target",
    "quantile_bucket",
    "rows",
    "min_model_prob",
    "max_model_prob",
    "avg_model_prob",
    "actual_rate",
    "absolute_gap",
]

CALIBRATION_SUMMARY_COLUMNS = [
    "target",
    "rows",
    "actual_rate",
    "avg_model_prob",
    "expected_calibration_error",
    "calibration_intercept",
    "calibration_slope",
]


class RollingValidationError(ValueError):
    """Raised when rolling-origin validation is not temporally valid."""


@dataclass(frozen=True)
class RollingFold:
    fold_id: str
    selection_date_from: str
    selection_date_to: str
    evaluation_date_from: str
    evaluation_date_to: str


def parse_fold(value: str) -> RollingFold:
    parts = [part.strip() for part in value.split("|")]
    if len(parts) != 5 or not all(parts):
        raise argparse.ArgumentTypeError(
            "fold must be ID|SELECTION_FROM|SELECTION_TO|EVALUATION_FROM|EVALUATION_TO"
        )
    return RollingFold(*parts)


def validate_folds(folds: list[RollingFold]) -> None:
    if not folds:
        raise RollingValidationError("at least one rolling fold is required")
    if len({fold.fold_id for fold in folds}) != len(folds):
        raise RollingValidationError("fold IDs must be unique")
    for fold in folds:
        try:
            selection_from = date.fromisoformat(fold.selection_date_from)
            selection_to = date.fromisoformat(fold.selection_date_to)
            evaluation_from = date.fromisoformat(fold.evaluation_date_from)
            evaluation_to = date.fromisoformat(fold.evaluation_date_to)
        except ValueError as exc:
            raise RollingValidationError(f"invalid ISO date in fold {fold.fold_id}") from exc
        if selection_from > selection_to:
            raise RollingValidationError(
                f"selection start follows selection end in fold {fold.fold_id}"
            )
        if selection_to >= evaluation_from:
            raise RollingValidationError(
                f"selection must end before evaluation starts in fold {fold.fold_id}"
            )
        if evaluation_from > evaluation_to:
            raise RollingValidationError(
                f"evaluation start follows evaluation end in fold {fold.fold_id}"
            )

    ordered = sorted(folds, key=lambda fold: fold.evaluation_date_from)
    for prior, current in zip(ordered, ordered[1:]):
        if prior.evaluation_date_to >= current.evaluation_date_from:
            raise RollingValidationError(
                f"evaluation windows overlap: {prior.fold_id} and {current.fold_id}"
            )


def select_parameters(
    inputs: SimulationBacktestInputs,
    date_from: str,
    date_to: str,
    half_lives: list[float],
    priors: list[float],
    variance_priors: list[float],
    max_events: int,
    simulations: int,
    seed: int,
    cut_size: int,
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    """Select a parameter set using only predictions inside one window."""
    candidates = []
    for half_life, prior, variance_prior in product(
        half_lives,
        priors,
        variance_priors,
    ):
        result = evaluate_simulation_backtest(
            inputs,
            date_from=date_from,
            date_to=date_to,
            max_events=max_events,
            simulations=simulations,
            seed=seed,
            cut_size=cut_size,
            half_life_days=half_life,
            prior_rounds=prior,
            variance_prior_rounds=variance_prior,
        )
        candidates.append(
            (
                selection_row(result, half_life, prior, variance_prior),
                result,
            )
        )
    selected_row, selected_result = max(
        candidates,
        key=lambda pair: (
            float(pair[0]["mean_brier_skill"]),
            -float(pair[0]["half_life_days"]),
            -float(pair[0]["prior_rounds"]),
            -float(pair[0]["variance_prior_rounds"]),
        ),
    )
    selected_row["selected"] = True
    return selected_row, selected_result, [pair[0] for pair in candidates]


def enriched_predictions(
    predictions: list[dict[str, object]],
    fold_id: str,
    selected: dict[str, object],
) -> list[dict[str, object]]:
    return [
        {
            "fold_id": fold_id,
            "half_life_days": selected["half_life_days"],
            "prior_rounds": selected["prior_rounds"],
            "variance_prior_rounds": selected["variance_prior_rounds"],
            **row,
        }
        for row in predictions
    ]


def paired_event_improvements(
    predictions: list[dict[str, object]],
    target: str,
) -> tuple[dict[str, float], dict[str, float]]:
    event_values: dict[str, list[float]] = {}
    fold_values: dict[str, list[float]] = {}
    for row in predictions:
        if row["target"] != target:
            continue
        actual = int(row["actual"])
        improvement = (
            (float(row["baseline_prob"]) - actual) ** 2
            - (float(row["model_prob"]) - actual) ** 2
        )
        event_key = f"{row['fold_id']}|{row['event_id']}"
        event_values.setdefault(event_key, []).append(improvement)
        fold_values.setdefault(str(row["fold_id"]), []).append(improvement)
    return (
        {key: sum(values) / len(values) for key, values in event_values.items()},
        {key: sum(values) / len(values) for key, values in fold_values.items()},
    )


def event_block_bootstrap(
    predictions: list[dict[str, object]],
    samples: int = 5000,
    seed: int = 20260729,
) -> list[dict[str, object]]:
    """Bootstrap paired Brier improvement using tournaments as the sample unit."""
    if samples <= 0:
        raise RollingValidationError("bootstrap samples must be positive")
    output = []
    for target_index, target in enumerate((*SELECTION_TARGETS, "winner")):
        event_effects, fold_effects = paired_event_improvements(predictions, target)
        if not event_effects:
            continue
        values = np.asarray(list(event_effects.values()), dtype=float)
        rng = np.random.default_rng(seed + target_index)
        sample_indices = rng.integers(0, len(values), size=(samples, len(values)))
        bootstrap_means = values[sample_indices].mean(axis=1)
        fold_effect_values = list(fold_effects.values())
        target_rows = [row for row in predictions if row["target"] == target]
        output.append(
            {
                "target": target,
                "events": len(values),
                "rows": len(target_rows),
                "mean_event_brier_improvement": round(float(values.mean()), 8),
                "ci_lower_95": round(float(np.quantile(bootstrap_means, 0.025)), 8),
                "ci_upper_95": round(float(np.quantile(bootstrap_means, 0.975)), 8),
                "bootstrap_probability_positive": round(
                    float((bootstrap_means > 0).mean()),
                    6,
                ),
                "positive_event_rate": round(float((values > 0).mean()), 6),
                "positive_fold_rate": round(
                    sum(value > 0 for value in fold_effect_values)
                    / len(fold_effect_values),
                    6,
                ),
                "worst_fold_brier_improvement": round(min(fold_effect_values), 8),
                "best_fold_brier_improvement": round(max(fold_effect_values), 8),
            }
        )
    return output


def calibration_coefficients(
    predictions: list[dict[str, object]],
) -> tuple[Optional[float], Optional[float]]:
    if len(predictions) < 3 or len({int(row["actual"]) for row in predictions}) < 2:
        return None, None
    probabilities = np.clip(
        np.asarray([float(row["model_prob"]) for row in predictions]),
        1e-6,
        1 - 1e-6,
    )
    logits = np.log(probabilities / (1 - probabilities))
    if float(np.ptp(logits)) <= 1e-12:
        return None, None
    outcomes = np.asarray([int(row["actual"]) for row in predictions], dtype=float)
    coefficients = np.asarray([0.0, 1.0])
    for _ in range(100):
        coefficients = np.clip(coefficients, -100.0, 100.0)
        linear = np.clip(coefficients[0] + coefficients[1] * logits, -30, 30)
        fitted = 1 / (1 + np.exp(-linear))
        weights = np.maximum(fitted * (1 - fitted), 1e-9)
        residuals = outcomes - fitted
        information_00 = float(weights.sum()) + 1e-8
        information_01 = float((weights * logits).sum())
        information_11 = float((weights * logits * logits).sum()) + 1e-8
        gradient_0 = float(residuals.sum())
        gradient_1 = float((residuals * logits).sum())
        determinant = (
            information_00 * information_11 - information_01 * information_01
        )
        if not np.isfinite(determinant) or abs(determinant) <= 1e-12:
            return None, None
        step = np.asarray(
            [
                (gradient_0 * information_11 - gradient_1 * information_01)
                / determinant,
                (information_00 * gradient_1 - information_01 * gradient_0)
                / determinant,
            ]
        )
        step = np.clip(step, -5.0, 5.0)
        coefficients += step
        if float(np.max(np.abs(step))) < 1e-9:
            break
    if np.any(~np.isfinite(coefficients)):
        return None, None
    return float(coefficients[0]), float(coefficients[1])


def quantile_calibration(
    predictions: list[dict[str, object]],
    bin_count: int = 10,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if bin_count <= 0:
        raise RollingValidationError("calibration bin count must be positive")
    buckets = []
    summaries = []
    for target in (*SELECTION_TARGETS, "winner"):
        rows = sorted(
            (row for row in predictions if row["target"] == target),
            key=lambda row: (float(row["model_prob"]), str(row["event_id"])),
        )
        if not rows:
            continue
        actual_bin_count = min(bin_count, len(rows))
        target_buckets = []
        for bucket_index in range(actual_bin_count):
            start = bucket_index * len(rows) // actual_bin_count
            end = (bucket_index + 1) * len(rows) // actual_bin_count
            selected = rows[start:end]
            probabilities = [float(row["model_prob"]) for row in selected]
            actual_rate = sum(int(row["actual"]) for row in selected) / len(selected)
            average_probability = sum(probabilities) / len(probabilities)
            target_buckets.append(
                {
                    "target": target,
                    "quantile_bucket": bucket_index + 1,
                    "rows": len(selected),
                    "min_model_prob": round(min(probabilities), 6),
                    "max_model_prob": round(max(probabilities), 6),
                    "avg_model_prob": round(average_probability, 6),
                    "actual_rate": round(actual_rate, 6),
                    "absolute_gap": round(abs(actual_rate - average_probability), 6),
                }
            )
        buckets.extend(target_buckets)
        intercept, slope = calibration_coefficients(rows)
        ece = sum(
            int(row["rows"]) * float(row["absolute_gap"]) for row in target_buckets
        ) / len(rows)
        summaries.append(
            {
                "target": target,
                "rows": len(rows),
                "actual_rate": round(
                    sum(int(row["actual"]) for row in rows) / len(rows),
                    6,
                ),
                "avg_model_prob": round(
                    sum(float(row["model_prob"]) for row in rows) / len(rows),
                    6,
                ),
                "expected_calibration_error": round(ece, 6),
                "calibration_intercept": "" if intercept is None else round(intercept, 6),
                "calibration_slope": "" if slope is None else round(slope, 6),
            }
        )
    return buckets, summaries


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def render_report(
    folds: list[dict[str, object]],
    aggregate_metrics: list[dict[str, object]],
    bootstrap: list[dict[str, object]],
    calibration_summary: list[dict[str, object]],
    manifest: dict[str, object],
) -> str:
    lines = [
        "# Rolling-Origin Tournament Simulation Validation",
        "",
        "Each fold selects parameters using only its selection window, freezes",
        "them, and scores the following non-overlapping evaluation window.",
        "Uncertainty resamples whole tournaments rather than player rows.",
        "",
        "## Fold Selections",
        "",
        "| Fold | Selection | Evaluation | Half-life | Mean prior | Variance prior | Eval events |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for row in folds:
        lines.append(
            "| {fold_id} | {selection_date_from} to {selection_date_to} | "
            "{evaluation_date_from} to {evaluation_date_to} | {half_life_days} | "
            "{prior_rounds} | {variance_prior_rounds} | {evaluation_events} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "## Aggregate Out-of-Sample Metrics",
            "",
            "| Target | Rows | Model Brier | Baseline Brier | Improvement |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in aggregate_metrics:
        lines.append(
            "| {target} | {rows} | {model_brier:.4f} | {baseline_brier:.4f} | "
            "{brier_improvement:+.4f} |".format(
                target=row["target"],
                rows=row["rows"],
                model_brier=float(row["model_brier"]),
                baseline_brier=float(row["baseline_brier"]),
                brier_improvement=float(row["brier_improvement"]),
            )
        )
    lines.extend(
        [
            "",
            "## Event-Block Bootstrap",
            "",
            "| Target | Events | Mean improvement | 95% CI | P(positive) | Positive events | Positive folds |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in bootstrap:
        lines.append(
            "| {target} | {events} | {mean_event_brier_improvement:+.4f} | "
            "[{ci_lower_95:+.4f}, {ci_upper_95:+.4f}] | "
            "{bootstrap_probability_positive:.3f} | {positive_event_rate:.3f} | "
            "{positive_fold_rate:.3f} |".format(
                target=row["target"],
                events=row["events"],
                mean_event_brier_improvement=float(row["mean_event_brier_improvement"]),
                ci_lower_95=float(row["ci_lower_95"]),
                ci_upper_95=float(row["ci_upper_95"]),
                bootstrap_probability_positive=float(
                    row["bootstrap_probability_positive"]
                ),
                positive_event_rate=float(row["positive_event_rate"]),
                positive_fold_rate=float(row["positive_fold_rate"]),
            )
        )
    lines.extend(
        [
            "",
            "## Calibration",
            "",
            "Ideal calibration has intercept 0 and slope 1. ECE is the",
            "probability-weighted absolute gap across equal-frequency buckets.",
            "",
            "| Target | ECE | Intercept | Slope |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in calibration_summary:
        lines.append(
            "| {target} | {expected_calibration_error:.4f} | {intercept} | {slope} |".format(
                target=row["target"],
                expected_calibration_error=float(row["expected_calibration_error"]),
                intercept=row["calibration_intercept"],
                slope=row["calibration_slope"],
            )
        )
    frozen = manifest["frozen_model"]
    assert isinstance(frozen, dict)
    lines.extend(
        [
            "",
            "Bootstrap intervals describe event-sampling variation conditional",
            "on the completed fold selections; they do not rerun parameter",
            "selection inside every bootstrap sample.",
            "",
            "## Frozen Future Model",
            "",
            f"- selection data: {frozen['selection_date_from']} through {frozen['selection_date_to']}",
            f"- half-life days: {frozen['half_life_days']}",
            f"- mean prior rounds: {frozen['prior_rounds']}",
            f"- variance prior rounds: {frozen['variance_prior_rounds']}",
            f"- source data through: {frozen['source_data_through']}",
            f"- prospective holdout must start after: {frozen['prospective_holdout_after']}",
            "",
            "The frozen configuration is awaiting genuinely future events. This",
            "is performance-model validation, not evidence of a betting edge.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def run_rolling_simulation_validation(
    canonical_dir: Path,
    round_performance_path: Path,
    output_dir: Path,
    folds: list[RollingFold],
    half_life_grid: list[float],
    prior_rounds_grid: list[float],
    variance_prior_rounds_grid: list[float],
    freeze_date_from: str,
    freeze_date_to: str,
    max_selection_events: int = 0,
    max_evaluation_events: int = 0,
    selection_simulations: int = 500,
    evaluation_simulations: int = 2000,
    bootstrap_samples: int = 5000,
    calibration_bins: int = 10,
    seed: int = 20260729,
    cut_size: int = 65,
) -> dict[str, object]:
    validate_folds(folds)
    try:
        freeze_from = date.fromisoformat(freeze_date_from)
        freeze_to = date.fromisoformat(freeze_date_to)
    except ValueError as exc:
        raise RollingValidationError("freeze dates must be ISO dates") from exc
    if freeze_from > freeze_to:
        raise RollingValidationError("freeze start must not follow freeze end")
    if selection_simulations <= 0 or evaluation_simulations <= 0:
        raise RollingValidationError("simulation counts must be positive")

    half_lives = validated_grid(half_life_grid, "half-life")
    priors = validated_grid(prior_rounds_grid, "prior-rounds", allow_zero=True)
    variance_priors = validated_grid(
        variance_prior_rounds_grid,
        "variance-prior-rounds",
        allow_zero=True,
    )
    inputs = prepare_backtest_inputs(canonical_dir, round_performance_path)
    fold_rows = []
    fold_metrics = []
    all_predictions: list[dict[str, object]] = []
    for fold_index, fold in enumerate(folds):
        fold_seed = seed + fold_index * 10_000
        selected, selection_result, _ = select_parameters(
            inputs,
            fold.selection_date_from,
            fold.selection_date_to,
            half_lives,
            priors,
            variance_priors,
            max_selection_events,
            selection_simulations,
            fold_seed,
            cut_size,
        )
        evaluation = evaluate_simulation_backtest(
            inputs,
            date_from=fold.evaluation_date_from,
            date_to=fold.evaluation_date_to,
            max_events=max_evaluation_events,
            simulations=evaluation_simulations,
            seed=fold_seed + 1_000_000,
            cut_size=cut_size,
            half_life_days=float(selected["half_life_days"]),
            prior_rounds=float(selected["prior_rounds"]),
            variance_prior_rounds=float(selected["variance_prior_rounds"]),
        )
        selection_events = selection_result["event_summaries"]
        evaluation_events = evaluation["event_summaries"]
        predictions = evaluation["predictions"]
        metrics = evaluation["metrics"]
        assert isinstance(selection_events, list)
        assert isinstance(evaluation_events, list)
        assert isinstance(predictions, list)
        assert isinstance(metrics, list)
        fold_row = {
            "fold_id": fold.fold_id,
            "selection_date_from": fold.selection_date_from,
            "selection_date_to": fold.selection_date_to,
            "evaluation_date_from": fold.evaluation_date_from,
            "evaluation_date_to": fold.evaluation_date_to,
            "half_life_days": selected["half_life_days"],
            "prior_rounds": selected["prior_rounds"],
            "variance_prior_rounds": selected["variance_prior_rounds"],
            "selection_mean_brier_skill": selected["mean_brier_skill"],
            "selection_events": len(selection_events),
            "evaluation_events": len(evaluation_events),
        }
        fold_rows.append(fold_row)
        fold_metrics.extend({"fold_id": fold.fold_id, **row} for row in metrics)
        all_predictions.extend(enriched_predictions(predictions, fold.fold_id, selected))

    aggregate_metrics = metric_rows(all_predictions)
    bootstrap = event_block_bootstrap(all_predictions, bootstrap_samples, seed)
    calibration, calibration_summary = quantile_calibration(
        all_predictions,
        calibration_bins,
    )

    frozen_selected, frozen_selection_result, frozen_grid = select_parameters(
        inputs,
        freeze_date_from,
        freeze_date_to,
        half_lives,
        priors,
        variance_priors,
        max_selection_events,
        selection_simulations,
        seed + 2_000_000,
        cut_size,
    )
    frozen_events = frozen_selection_result["event_summaries"]
    assert isinstance(frozen_events, list)
    frozen_event_ids = {str(row["event_id"]) for row in frozen_events}
    completed_dates = [
        event.get("date_end") or event["date_start"]
        for event in inputs.events
        if event["event_id"] in frozen_event_ids
    ]
    source_data_through = max(completed_dates) if completed_dates else freeze_date_to
    created_at = datetime.now(timezone.utc)
    prospective_holdout_after = max(
        source_data_through,
        created_at.date().isoformat(),
    )
    manifest = {
        "manifest_version": 1,
        "created_at_utc": created_at.isoformat(),
        "status": "frozen_awaiting_future_evaluation",
        "selection_protocol": "rolling_origin_validation_then_latest_window_freeze",
        "selection_objective": "mean_normalized_brier_improvement",
        "selection_targets": list(SELECTION_TARGETS),
        "seed": seed,
        "cut_size": cut_size,
        "canonical_dir": str(canonical_dir),
        "round_performance_path": str(round_performance_path),
        "input_sha256": {
            "events": file_sha256(canonical_dir / "events.csv"),
            "player_event_results": file_sha256(
                canonical_dir / "player_event_results.csv"
            ),
            "round_performance": file_sha256(round_performance_path),
        },
        "grid": {
            "half_life_days": half_lives,
            "prior_rounds": priors,
            "variance_prior_rounds": variance_priors,
        },
        "rolling_folds": [row.copy() for row in fold_rows],
        "frozen_model": {
            "selection_date_from": freeze_date_from,
            "selection_date_to": freeze_date_to,
            "source_data_through": source_data_through,
            "selection_events": len(frozen_events),
            "half_life_days": frozen_selected["half_life_days"],
            "prior_rounds": frozen_selected["prior_rounds"],
            "variance_prior_rounds": frozen_selected["variance_prior_rounds"],
            "selection_mean_brier_skill": frozen_selected["mean_brier_skill"],
            "prospective_holdout_after": prospective_holdout_after,
            "next_evaluation_rule": (
                "event_date_start must be after both source_data_through and "
                "the UTC model-freeze date"
            ),
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "predictions_path": output_dir / "out_of_sample_predictions.csv",
        "folds_path": output_dir / "folds.csv",
        "fold_metrics_path": output_dir / "fold_metrics.csv",
        "aggregate_metrics_path": output_dir / "aggregate_metrics.csv",
        "bootstrap_path": output_dir / "event_bootstrap.csv",
        "calibration_path": output_dir / "calibration.csv",
        "calibration_summary_path": output_dir / "calibration_summary.csv",
        "frozen_grid_path": output_dir / "frozen_selection_grid.csv",
        "manifest_path": output_dir / "frozen_model_manifest.json",
        "report_path": output_dir / "report.md",
    }
    write_csv(paths["predictions_path"], ROLLING_PREDICTION_COLUMNS, all_predictions)
    write_csv(paths["folds_path"], FOLD_COLUMNS, fold_rows)
    write_csv(paths["fold_metrics_path"], FOLD_METRIC_COLUMNS, fold_metrics)
    write_csv(paths["aggregate_metrics_path"], METRIC_COLUMNS, aggregate_metrics)
    write_csv(paths["bootstrap_path"], BOOTSTRAP_COLUMNS, bootstrap)
    write_csv(paths["calibration_path"], CALIBRATION_COLUMNS, calibration)
    write_csv(
        paths["calibration_summary_path"],
        CALIBRATION_SUMMARY_COLUMNS,
        calibration_summary,
    )
    frozen_grid.sort(
        key=lambda row: (
            -float(row["mean_brier_skill"]),
            float(row["half_life_days"]),
            float(row["prior_rounds"]),
            float(row["variance_prior_rounds"]),
        )
    )
    write_csv(
        paths["frozen_grid_path"],
        list(frozen_grid[0]),
        frozen_grid,
    )
    paths["manifest_path"].write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths["report_path"].write_text(
        render_report(
            fold_rows,
            aggregate_metrics,
            bootstrap,
            calibration_summary,
            manifest,
        ),
        encoding="utf-8",
    )
    return {
        "folds": fold_rows,
        "fold_metrics": fold_metrics,
        "predictions": all_predictions,
        "aggregate_metrics": aggregate_metrics,
        "bootstrap": bootstrap,
        "calibration": calibration,
        "calibration_summary": calibration_summary,
        "manifest": manifest,
        **paths,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="rolling-simulation-validation")
    parser.add_argument("--canonical-dir", required=True, type=Path)
    parser.add_argument("--round-performance", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--fold", action="append", required=True, type=parse_fold)
    parser.add_argument("--half-life-grid", type=comma_separated_floats, default=[90, 180, 365])
    parser.add_argument("--prior-rounds-grid", type=comma_separated_floats, default=[8, 20, 40])
    parser.add_argument(
        "--variance-prior-rounds-grid",
        type=comma_separated_floats,
        default=[20],
    )
    parser.add_argument("--freeze-date-from", required=True)
    parser.add_argument("--freeze-date-to", required=True)
    parser.add_argument("--max-selection-events", type=int, default=0)
    parser.add_argument("--max-evaluation-events", type=int, default=0)
    parser.add_argument("--selection-simulations", type=int, default=500)
    parser.add_argument("--evaluation-simulations", type=int, default=2000)
    parser.add_argument("--bootstrap-samples", type=int, default=5000)
    parser.add_argument("--calibration-bins", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--cut-size", type=int, default=65)
    args = parser.parse_args(argv)
    result = run_rolling_simulation_validation(
        args.canonical_dir,
        args.round_performance,
        args.output_dir,
        args.fold,
        args.half_life_grid,
        args.prior_rounds_grid,
        args.variance_prior_rounds_grid,
        args.freeze_date_from,
        args.freeze_date_to,
        max_selection_events=args.max_selection_events,
        max_evaluation_events=args.max_evaluation_events,
        selection_simulations=args.selection_simulations,
        evaluation_simulations=args.evaluation_simulations,
        bootstrap_samples=args.bootstrap_samples,
        calibration_bins=args.calibration_bins,
        seed=args.seed,
        cut_size=args.cut_size,
    )
    print(f"rolling_validation_report={result['report_path']}")
    print(f"rolling_validation_metrics={result['aggregate_metrics_path']}")
    print(f"rolling_validation_manifest={result['manifest_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
