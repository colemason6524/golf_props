"""Paired rolling-origin evaluation of course history versus the incumbent."""

from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timezone
from itertools import product
from pathlib import Path
from typing import Optional

from golf_props.backtest.rolling_simulation_validation import (
    RollingFold,
    comma_separated_floats,
    event_block_bootstrap,
    file_sha256,
    parse_fold,
    quantile_calibration,
    select_parameters,
    validate_folds,
)
from golf_props.backtest.simulation_backtest import (
    METRIC_COLUMNS,
    SimulationBacktestInputs,
    clip_probability,
    evaluate_simulation_backtest,
    metric_rows,
    prepare_backtest_inputs,
    write_csv,
)
from golf_props.backtest.simulation_selection import (
    SELECTION_TARGETS,
    validated_grid,
)
from golf_props.models.course_adjustment import (
    PreparedCourseHistory,
    apply_course_adjustment,
    prepare_course_history,
)

PAIRED_PREDICTION_COLUMNS = [
    "fold_id",
    "event_id",
    "event_name",
    "event_date",
    "target",
    "player_id",
    "player_name",
    "actual",
    "incumbent_prob",
    "challenger_prob",
    "structural_baseline_prob",
    "half_life_days",
    "prior_rounds",
    "variance_prior_rounds",
    "course_adjustment_weight",
    "course_prior_rounds",
]

PAIRED_METRIC_COLUMNS = [
    "target",
    "events",
    "rows",
    "incumbent_brier",
    "challenger_brier",
    "brier_improvement",
    "incumbent_log_loss",
    "challenger_log_loss",
    "log_loss_improvement",
]

FOLD_PAIRED_METRIC_COLUMNS = ["fold_id", *PAIRED_METRIC_COLUMNS]

FOLD_COLUMNS = [
    "fold_id",
    "selection_date_from",
    "selection_date_to",
    "evaluation_date_from",
    "evaluation_date_to",
    "half_life_days",
    "prior_rounds",
    "variance_prior_rounds",
    "course_adjustment_weight",
    "course_prior_rounds",
    "course_selection_mean_brier_skill",
    "selection_events",
    "evaluation_events",
    "course_history_player_rate",
    "average_absolute_course_adjustment",
]

COURSE_SELECTION_COLUMNS = [
    "fold_id",
    "course_adjustment_weight",
    "course_prior_rounds",
    "mean_brier_skill_vs_incumbent",
    "make_cut_brier_skill_vs_incumbent",
    "top20_brier_skill_vs_incumbent",
    "top10_brier_skill_vs_incumbent",
    "top5_brier_skill_vs_incumbent",
    "selected",
]


class CourseChallengerError(ValueError):
    """Raised when a paired course challenger experiment cannot be run."""


def prediction_key(row: dict[str, object]) -> tuple[str, str, str]:
    return str(row["event_id"]), str(row["target"]), str(row["player_id"])


def pair_predictions(
    incumbent: list[dict[str, object]],
    challenger: list[dict[str, object]],
    fold_id: str,
    strength_parameters: dict[str, object],
    course_parameters: dict[str, object],
) -> list[dict[str, object]]:
    incumbent_by_key = {prediction_key(row): row for row in incumbent}
    challenger_by_key = {prediction_key(row): row for row in challenger}
    if set(incumbent_by_key) != set(challenger_by_key):
        raise CourseChallengerError(
            "incumbent and challenger prediction keys do not match"
        )
    output = []
    for key in sorted(incumbent_by_key):
        incumbent_row = incumbent_by_key[key]
        challenger_row = challenger_by_key[key]
        if incumbent_row["actual"] != challenger_row["actual"]:
            raise CourseChallengerError("paired predictions disagree on actual result")
        output.append(
            {
                "fold_id": fold_id,
                "event_id": incumbent_row["event_id"],
                "event_name": incumbent_row["event_name"],
                "event_date": incumbent_row["event_date"],
                "target": incumbent_row["target"],
                "player_id": incumbent_row["player_id"],
                "player_name": incumbent_row["player_name"],
                "actual": incumbent_row["actual"],
                "incumbent_prob": incumbent_row["model_prob"],
                "challenger_prob": challenger_row["model_prob"],
                "structural_baseline_prob": incumbent_row["baseline_prob"],
                "half_life_days": strength_parameters["half_life_days"],
                "prior_rounds": strength_parameters["prior_rounds"],
                "variance_prior_rounds": strength_parameters[
                    "variance_prior_rounds"
                ],
                "course_adjustment_weight": course_parameters[
                    "course_adjustment_weight"
                ],
                "course_prior_rounds": course_parameters["course_prior_rounds"],
            }
        )
    return output


def paired_metrics(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    output = []
    for target in (*SELECTION_TARGETS, "winner"):
        selected = [row for row in rows if row["target"] == target]
        if not selected:
            continue
        incumbent_brier = sum(
            (float(row["incumbent_prob"]) - int(row["actual"])) ** 2
            for row in selected
        ) / len(selected)
        challenger_brier = sum(
            (float(row["challenger_prob"]) - int(row["actual"])) ** 2
            for row in selected
        ) / len(selected)

        def average_log_loss(column: str) -> float:
            total = 0.0
            for row in selected:
                actual = int(row["actual"])
                probability = clip_probability(float(row[column]))
                total -= actual * math.log(probability) + (1 - actual) * math.log(
                    1 - probability
                )
            return total / len(selected)

        incumbent_log_loss = average_log_loss("incumbent_prob")
        challenger_log_loss = average_log_loss("challenger_prob")
        output.append(
            {
                "target": target,
                "events": len({row["event_id"] for row in selected}),
                "rows": len(selected),
                "incumbent_brier": round(incumbent_brier, 8),
                "challenger_brier": round(challenger_brier, 8),
                "brier_improvement": round(incumbent_brier - challenger_brier, 8),
                "incumbent_log_loss": round(incumbent_log_loss, 8),
                "challenger_log_loss": round(challenger_log_loss, 8),
                "log_loss_improvement": round(
                    incumbent_log_loss - challenger_log_loss,
                    8,
                ),
            }
        )
    return output


def course_transform(
    inputs: SimulationBacktestInputs,
    course_history: PreparedCourseHistory,
    half_life_days: float,
    course_prior_rounds: float,
    adjustment_weight: float,
    max_absolute_adjustment: float,
):
    def transform(
        strength_rows: list[dict[str, object]],
        event: dict[str, str],
    ) -> list[dict[str, object]]:
        return apply_course_adjustment(
            strength_rows,
            inputs.course_by_event.get(event["event_id"], ""),
            event["date_start"],
            course_history,
            half_life_days,
            course_prior_rounds,
            adjustment_weight,
            max_absolute_adjustment,
        )

    return transform


def course_selection_row(
    incumbent: dict[str, object],
    challenger: dict[str, object],
    fold_id: str,
    adjustment_weight: float,
    course_prior_rounds: float,
) -> dict[str, object]:
    incumbent_predictions = incumbent["predictions"]
    challenger_predictions = challenger["predictions"]
    assert isinstance(incumbent_predictions, list)
    assert isinstance(challenger_predictions, list)
    pairs = pair_predictions(
        incumbent_predictions,
        challenger_predictions,
        fold_id,
        incumbent["parameters"],
        {
            "course_adjustment_weight": adjustment_weight,
            "course_prior_rounds": course_prior_rounds,
        },
    )
    metrics = {str(row["target"]): row for row in paired_metrics(pairs)}
    skills = {}
    for target in SELECTION_TARGETS:
        metric = metrics.get(target)
        incumbent_brier = float(metric["incumbent_brier"]) if metric else 0.0
        skills[target] = (
            None
            if metric is None or incumbent_brier <= 0
            else float(metric["brier_improvement"]) / incumbent_brier
        )
    available = [value for value in skills.values() if value is not None]
    if not available:
        raise CourseChallengerError("no usable course-selection metrics")
    return {
        "fold_id": fold_id,
        "course_adjustment_weight": adjustment_weight,
        "course_prior_rounds": course_prior_rounds,
        "mean_brier_skill_vs_incumbent": round(sum(available) / len(available), 8),
        **{
            f"{target}_brier_skill_vs_incumbent": (
                "" if skills[target] is None else round(float(skills[target]), 8)
            )
            for target in SELECTION_TARGETS
        },
        "selected": False,
    }


def select_course_parameters(
    inputs: SimulationBacktestInputs,
    course_history: PreparedCourseHistory,
    incumbent_result: dict[str, object],
    fold_id: str,
    date_from: str,
    date_to: str,
    strength_parameters: dict[str, object],
    weights: list[float],
    course_priors: list[float],
    max_events: int,
    simulations: int,
    seed: int,
    cut_size: int,
    max_absolute_adjustment: float,
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    candidates = []
    for weight, course_prior in product(weights, course_priors):
        if weight == 0 and course_prior != course_priors[0]:
            continue
        challenger = evaluate_simulation_backtest(
            inputs,
            date_from=date_from,
            date_to=date_to,
            max_events=max_events,
            simulations=simulations,
            seed=seed,
            cut_size=cut_size,
            half_life_days=float(strength_parameters["half_life_days"]),
            prior_rounds=float(strength_parameters["prior_rounds"]),
            variance_prior_rounds=float(
                strength_parameters["variance_prior_rounds"]
            ),
            strength_transform=course_transform(
                inputs,
                course_history,
                float(strength_parameters["half_life_days"]),
                course_prior,
                weight,
                max_absolute_adjustment,
            ),
        )
        row = course_selection_row(
            incumbent_result,
            challenger,
            fold_id,
            weight,
            course_prior,
        )
        candidates.append((row, challenger))
    selected_row, selected_result = max(
        candidates,
        key=lambda pair: (
            float(pair[0]["mean_brier_skill_vs_incumbent"]),
            -float(pair[0]["course_adjustment_weight"]),
            float(pair[0]["course_prior_rounds"]),
        ),
    )
    selected_row["selected"] = True
    return selected_row, selected_result, [row for row, _ in candidates]


def model_predictions_from_pairs(
    rows: list[dict[str, object]],
    probability_column: str,
) -> list[dict[str, object]]:
    return [
        {
            "event_id": row["event_id"],
            "event_name": row["event_name"],
            "event_date": row["event_date"],
            "target": row["target"],
            "player_id": row["player_id"],
            "player_name": row["player_name"],
            "actual": row["actual"],
            "model_prob": row[probability_column],
            "baseline_prob": row["structural_baseline_prob"],
            "fold_id": row["fold_id"],
        }
        for row in rows
    ]


def paired_bootstrap_input(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "fold_id": row["fold_id"],
            "event_id": row["event_id"],
            "target": row["target"],
            "actual": row["actual"],
            "model_prob": row["challenger_prob"],
            "baseline_prob": row["incumbent_prob"],
        }
        for row in rows
    ]


def render_report(
    folds: list[dict[str, object]],
    paired: list[dict[str, object]],
    bootstrap: list[dict[str, object]],
    incumbent_calibration: list[dict[str, object]],
    challenger_calibration: list[dict[str, object]],
    manifest: dict[str, object],
) -> str:
    lines = [
        "# Course-Residual Challenger Validation",
        "",
        "The incumbent is selected and frozen inside each fold. The challenger",
        "adds only prior same-course performance beyond each player's general",
        "level, with course shrinkage selected in the same historical window.",
        "",
        "## Fold Selections",
        "",
        "| Fold | Strength half-life | Mean prior | Course weight | Course prior | Eval events | Course-history players |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in folds:
        lines.append(
            "| {fold_id} | {half_life_days} | {prior_rounds} | "
            "{course_adjustment_weight} | {course_prior_rounds} | "
            "{evaluation_events} | {course_history_player_rate:.3f} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "## Paired Out-of-Sample Metrics",
            "",
            "Positive improvement means the course challenger beat the incumbent.",
            "",
            "| Target | Rows | Incumbent Brier | Challenger Brier | Improvement | Log-loss improvement |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in paired:
        lines.append(
            "| {target} | {rows} | {incumbent_brier:.5f} | "
            "{challenger_brier:.5f} | {brier_improvement:+.5f} | "
            "{log_loss_improvement:+.5f} |".format(
                target=row["target"],
                rows=row["rows"],
                incumbent_brier=float(row["incumbent_brier"]),
                challenger_brier=float(row["challenger_brier"]),
                brier_improvement=float(row["brier_improvement"]),
                log_loss_improvement=float(row["log_loss_improvement"]),
            )
        )
    lines.extend(
        [
            "",
            "## Paired Event Bootstrap",
            "",
            "| Target | Events | Mean improvement | 95% CI | Positive events | Positive folds |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in bootstrap:
        lines.append(
            "| {target} | {events} | {mean_event_brier_improvement:+.5f} | "
            "[{ci_lower_95:+.5f}, {ci_upper_95:+.5f}] | "
            "{positive_event_rate:.3f} | {positive_fold_rate:.3f} |".format(
                target=row["target"],
                events=row["events"],
                mean_event_brier_improvement=float(row["mean_event_brier_improvement"]),
                ci_lower_95=float(row["ci_lower_95"]),
                ci_upper_95=float(row["ci_upper_95"]),
                positive_event_rate=float(row["positive_event_rate"]),
                positive_fold_rate=float(row["positive_fold_rate"]),
            )
        )
    incumbent_by_target = {str(row["target"]): row for row in incumbent_calibration}
    challenger_by_target = {str(row["target"]): row for row in challenger_calibration}
    lines.extend(
        [
            "",
            "## Calibration Comparison",
            "",
            "| Target | Incumbent ECE | Challenger ECE | Incumbent slope | Challenger slope |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for target in (*SELECTION_TARGETS, "winner"):
        incumbent = incumbent_by_target.get(target)
        challenger = challenger_by_target.get(target)
        if incumbent is None or challenger is None:
            continue
        lines.append(
            f"| {target} | {float(incumbent['expected_calibration_error']):.4f} | "
            f"{float(challenger['expected_calibration_error']):.4f} | "
            f"{incumbent['calibration_slope']} | {challenger['calibration_slope']} |"
        )
    frozen = manifest["frozen_challenger"]
    assert isinstance(frozen, dict)
    lines.extend(
        [
            "",
            "## Frozen Research Challenger",
            "",
            f"- course adjustment weight: {frozen['course_adjustment_weight']}",
            f"- course prior rounds: {frozen['course_prior_rounds']}",
            f"- players with matched course history: {frozen['course_history_player_rate']}",
            f"- prospective holdout must start after: {frozen['prospective_holdout_after']}",
            "",
            "The incumbent remains the production reference until the paired",
            "results justify promotion. This is not evidence of a betting edge.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def run_course_challenger_validation(
    canonical_dir: Path,
    round_performance_path: Path,
    output_dir: Path,
    folds: list[RollingFold],
    half_life_grid: list[float],
    prior_rounds_grid: list[float],
    variance_prior_rounds_grid: list[float],
    course_weight_grid: list[float],
    course_prior_rounds_grid: list[float],
    freeze_date_from: str,
    freeze_date_to: str,
    max_selection_events: int = 20,
    max_evaluation_events: int = 0,
    selection_simulations: int = 300,
    evaluation_simulations: int = 1000,
    bootstrap_samples: int = 5000,
    calibration_bins: int = 10,
    seed: int = 20260729,
    cut_size: int = 65,
    max_absolute_adjustment: float = 2.0,
) -> dict[str, object]:
    validate_folds(folds)
    try:
        freeze_from = date.fromisoformat(freeze_date_from)
        freeze_to = date.fromisoformat(freeze_date_to)
    except ValueError as exc:
        raise CourseChallengerError("freeze dates must be ISO dates") from exc
    if freeze_from > freeze_to:
        raise CourseChallengerError("freeze start must not follow freeze end")
    if max_absolute_adjustment < 0:
        raise CourseChallengerError("max course adjustment cannot be negative")
    half_lives = validated_grid(half_life_grid, "half-life")
    priors = validated_grid(prior_rounds_grid, "prior-rounds", allow_zero=True)
    variance_priors = validated_grid(
        variance_prior_rounds_grid,
        "variance-prior-rounds",
        allow_zero=True,
    )
    course_weights = validated_grid(
        course_weight_grid,
        "course-weight",
        allow_zero=True,
    )
    course_priors = validated_grid(
        course_prior_rounds_grid,
        "course-prior-rounds",
        allow_zero=True,
    )
    inputs = prepare_backtest_inputs(canonical_dir, round_performance_path)
    course_history = prepare_course_history(inputs.round_rows)

    fold_rows = []
    selection_rows = []
    all_pairs = []
    fold_paired = []
    for fold_index, fold in enumerate(folds):
        fold_seed = seed + fold_index * 10_000
        strength_selected, incumbent_selection, _ = select_parameters(
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
        strength_parameters = {
            "half_life_days": strength_selected["half_life_days"],
            "prior_rounds": strength_selected["prior_rounds"],
            "variance_prior_rounds": strength_selected["variance_prior_rounds"],
        }
        course_selected, _, course_grid = select_course_parameters(
            inputs,
            course_history,
            incumbent_selection,
            fold.fold_id,
            fold.selection_date_from,
            fold.selection_date_to,
            strength_parameters,
            course_weights,
            course_priors,
            max_selection_events,
            selection_simulations,
            fold_seed,
            cut_size,
            max_absolute_adjustment,
        )
        selection_rows.extend(course_grid)
        incumbent_evaluation = evaluate_simulation_backtest(
            inputs,
            date_from=fold.evaluation_date_from,
            date_to=fold.evaluation_date_to,
            max_events=max_evaluation_events,
            simulations=evaluation_simulations,
            seed=fold_seed + 1_000_000,
            cut_size=cut_size,
            half_life_days=float(strength_parameters["half_life_days"]),
            prior_rounds=float(strength_parameters["prior_rounds"]),
            variance_prior_rounds=float(
                strength_parameters["variance_prior_rounds"]
            ),
        )
        challenger_evaluation = evaluate_simulation_backtest(
            inputs,
            date_from=fold.evaluation_date_from,
            date_to=fold.evaluation_date_to,
            max_events=max_evaluation_events,
            simulations=evaluation_simulations,
            seed=fold_seed + 1_000_000,
            cut_size=cut_size,
            half_life_days=float(strength_parameters["half_life_days"]),
            prior_rounds=float(strength_parameters["prior_rounds"]),
            variance_prior_rounds=float(
                strength_parameters["variance_prior_rounds"]
            ),
            strength_transform=course_transform(
                inputs,
                course_history,
                float(strength_parameters["half_life_days"]),
                float(course_selected["course_prior_rounds"]),
                float(course_selected["course_adjustment_weight"]),
                max_absolute_adjustment,
            ),
        )
        incumbent_predictions = incumbent_evaluation["predictions"]
        challenger_predictions = challenger_evaluation["predictions"]
        event_summaries = challenger_evaluation["event_summaries"]
        selection_events = incumbent_selection["event_summaries"]
        assert isinstance(incumbent_predictions, list)
        assert isinstance(challenger_predictions, list)
        assert isinstance(event_summaries, list)
        assert isinstance(selection_events, list)
        pairs = pair_predictions(
            incumbent_predictions,
            challenger_predictions,
            fold.fold_id,
            strength_parameters,
            course_selected,
        )
        all_pairs.extend(pairs)
        fold_paired.extend(
            {"fold_id": fold.fold_id, **row} for row in paired_metrics(pairs)
        )
        total_players = sum(int(row["field_size"]) for row in event_summaries)
        course_history_players = sum(
            int(row["course_history_players"]) for row in event_summaries
        )
        fold_rows.append(
            {
                "fold_id": fold.fold_id,
                "selection_date_from": fold.selection_date_from,
                "selection_date_to": fold.selection_date_to,
                "evaluation_date_from": fold.evaluation_date_from,
                "evaluation_date_to": fold.evaluation_date_to,
                **strength_parameters,
                "course_adjustment_weight": course_selected[
                    "course_adjustment_weight"
                ],
                "course_prior_rounds": course_selected["course_prior_rounds"],
                "course_selection_mean_brier_skill": course_selected[
                    "mean_brier_skill_vs_incumbent"
                ],
                "selection_events": len(selection_events),
                "evaluation_events": len(event_summaries),
                "course_history_player_rate": round(
                    course_history_players / total_players if total_players else 0.0,
                    6,
                ),
                "average_absolute_course_adjustment": round(
                    sum(
                        float(row["average_absolute_course_adjustment"])
                        * int(row["field_size"])
                        for row in event_summaries
                    )
                    / total_players
                    if total_players
                    else 0.0,
                    6,
                ),
            }
        )

    incumbent_predictions = model_predictions_from_pairs(all_pairs, "incumbent_prob")
    challenger_predictions = model_predictions_from_pairs(all_pairs, "challenger_prob")
    incumbent_metrics = metric_rows(incumbent_predictions)
    challenger_metrics = metric_rows(challenger_predictions)
    paired = paired_metrics(all_pairs)
    bootstrap = event_block_bootstrap(
        paired_bootstrap_input(all_pairs),
        bootstrap_samples,
        seed,
    )
    _, incumbent_calibration = quantile_calibration(
        incumbent_predictions,
        calibration_bins,
    )
    _, challenger_calibration = quantile_calibration(
        challenger_predictions,
        calibration_bins,
    )

    frozen_strength, frozen_incumbent, _ = select_parameters(
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
    frozen_strength_parameters = {
        "half_life_days": frozen_strength["half_life_days"],
        "prior_rounds": frozen_strength["prior_rounds"],
        "variance_prior_rounds": frozen_strength["variance_prior_rounds"],
    }
    frozen_course, frozen_course_result, frozen_course_grid = select_course_parameters(
        inputs,
        course_history,
        frozen_incumbent,
        "frozen",
        freeze_date_from,
        freeze_date_to,
        frozen_strength_parameters,
        course_weights,
        course_priors,
        max_selection_events,
        selection_simulations,
        seed + 2_000_000,
        cut_size,
        max_absolute_adjustment,
    )
    frozen_events = frozen_incumbent["event_summaries"]
    frozen_course_events = frozen_course_result["event_summaries"]
    assert isinstance(frozen_events, list)
    assert isinstance(frozen_course_events, list)
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
    frozen_total_players = sum(
        int(row["field_size"]) for row in frozen_course_events
    )
    frozen_course_history_players = sum(
        int(row["course_history_players"]) for row in frozen_course_events
    )
    manifest = {
        "manifest_version": 1,
        "created_at_utc": created_at.isoformat(),
        "status": "research_challenger_frozen_awaiting_future_evaluation",
        "incumbent_status": "unchanged",
        "input_sha256": {
            "events": file_sha256(canonical_dir / "events.csv"),
            "event_courses": file_sha256(canonical_dir / "event_courses.csv"),
            "player_event_results": file_sha256(
                canonical_dir / "player_event_results.csv"
            ),
            "round_performance": file_sha256(round_performance_path),
        },
        "frozen_challenger": {
            **frozen_strength_parameters,
            "course_adjustment_weight": frozen_course["course_adjustment_weight"],
            "course_prior_rounds": frozen_course["course_prior_rounds"],
            "max_absolute_adjustment": max_absolute_adjustment,
            "selection_date_from": freeze_date_from,
            "selection_date_to": freeze_date_to,
            "source_data_through": source_data_through,
            "prospective_holdout_after": prospective_holdout_after,
            "course_history_player_rate": round(
                frozen_course_history_players / frozen_total_players
                if frozen_total_players
                else 0.0,
                6,
            ),
            "selection_mean_brier_skill_vs_incumbent": frozen_course[
                "mean_brier_skill_vs_incumbent"
            ],
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "report_path": output_dir / "report.md",
        "folds_path": output_dir / "folds.csv",
        "selection_path": output_dir / "course_selection_grid.csv",
        "predictions_path": output_dir / "paired_predictions.csv",
        "paired_metrics_path": output_dir / "paired_metrics.csv",
        "fold_metrics_path": output_dir / "fold_paired_metrics.csv",
        "bootstrap_path": output_dir / "paired_event_bootstrap.csv",
        "incumbent_metrics_path": output_dir / "incumbent_metrics.csv",
        "challenger_metrics_path": output_dir / "challenger_metrics.csv",
        "incumbent_calibration_path": output_dir / "incumbent_calibration_summary.csv",
        "challenger_calibration_path": output_dir / "challenger_calibration_summary.csv",
        "frozen_grid_path": output_dir / "frozen_course_selection_grid.csv",
        "manifest_path": output_dir / "challenger_manifest.json",
    }
    write_csv(paths["folds_path"], FOLD_COLUMNS, fold_rows)
    write_csv(paths["selection_path"], COURSE_SELECTION_COLUMNS, selection_rows)
    write_csv(paths["predictions_path"], PAIRED_PREDICTION_COLUMNS, all_pairs)
    write_csv(paths["paired_metrics_path"], PAIRED_METRIC_COLUMNS, paired)
    write_csv(
        paths["fold_metrics_path"],
        FOLD_PAIRED_METRIC_COLUMNS,
        fold_paired,
    )
    write_csv(paths["bootstrap_path"], list(bootstrap[0]), bootstrap)
    write_csv(paths["incumbent_metrics_path"], METRIC_COLUMNS, incumbent_metrics)
    write_csv(paths["challenger_metrics_path"], METRIC_COLUMNS, challenger_metrics)
    write_csv(
        paths["incumbent_calibration_path"],
        list(incumbent_calibration[0]),
        incumbent_calibration,
    )
    write_csv(
        paths["challenger_calibration_path"],
        list(challenger_calibration[0]),
        challenger_calibration,
    )
    frozen_course_grid.sort(
        key=lambda row: (
            -float(row["mean_brier_skill_vs_incumbent"]),
            float(row["course_adjustment_weight"]),
            -float(row["course_prior_rounds"]),
        )
    )
    write_csv(
        paths["frozen_grid_path"],
        COURSE_SELECTION_COLUMNS,
        frozen_course_grid,
    )
    paths["manifest_path"].write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths["report_path"].write_text(
        render_report(
            fold_rows,
            paired,
            bootstrap,
            incumbent_calibration,
            challenger_calibration,
            manifest,
        ),
        encoding="utf-8",
    )
    return {
        "folds": fold_rows,
        "selection_rows": selection_rows,
        "paired_predictions": all_pairs,
        "paired_metrics": paired,
        "fold_metrics": fold_paired,
        "bootstrap": bootstrap,
        "manifest": manifest,
        **paths,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="course-challenger-validation")
    parser.add_argument("--canonical-dir", required=True, type=Path)
    parser.add_argument("--round-performance", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--fold", action="append", required=True, type=parse_fold)
    parser.add_argument("--half-life-grid", type=comma_separated_floats, default=[90, 180, 365])
    parser.add_argument("--prior-rounds-grid", type=comma_separated_floats, default=[8, 20, 40])
    parser.add_argument("--variance-prior-rounds-grid", type=comma_separated_floats, default=[20])
    parser.add_argument("--course-weight-grid", type=comma_separated_floats, default=[0, 0.5, 1])
    parser.add_argument("--course-prior-rounds-grid", type=comma_separated_floats, default=[8, 20, 40])
    parser.add_argument("--freeze-date-from", required=True)
    parser.add_argument("--freeze-date-to", required=True)
    parser.add_argument("--max-selection-events", type=int, default=20)
    parser.add_argument("--max-evaluation-events", type=int, default=0)
    parser.add_argument("--selection-simulations", type=int, default=300)
    parser.add_argument("--evaluation-simulations", type=int, default=1000)
    parser.add_argument("--bootstrap-samples", type=int, default=5000)
    parser.add_argument("--calibration-bins", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--cut-size", type=int, default=65)
    parser.add_argument("--max-absolute-adjustment", type=float, default=2.0)
    args = parser.parse_args(argv)
    result = run_course_challenger_validation(
        args.canonical_dir,
        args.round_performance,
        args.output_dir,
        args.fold,
        args.half_life_grid,
        args.prior_rounds_grid,
        args.variance_prior_rounds_grid,
        args.course_weight_grid,
        args.course_prior_rounds_grid,
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
        max_absolute_adjustment=args.max_absolute_adjustment,
    )
    print(f"course_challenger_report={result['report_path']}")
    print(f"course_challenger_metrics={result['paired_metrics_path']}")
    print(f"course_challenger_manifest={result['manifest_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
