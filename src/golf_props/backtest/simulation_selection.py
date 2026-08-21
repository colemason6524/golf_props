"""Validation-only parameter selection with a later untouched test window."""

from __future__ import annotations

import argparse
import csv
import json
from itertools import product
from pathlib import Path
from typing import Optional

from golf_props.backtest.simulation_backtest import (
    SimulationBacktestError,
    evaluate_simulation_backtest,
    prepare_backtest_inputs,
    write_simulation_backtest_outputs,
)

SELECTION_TARGETS = ("make_cut", "top20", "top10", "top5")

SELECTION_COLUMNS = [
    "half_life_days",
    "prior_rounds",
    "variance_prior_rounds",
    "validation_events",
    "validation_prediction_rows",
    "mean_brier_skill",
    "make_cut_brier_skill",
    "top20_brier_skill",
    "top10_brier_skill",
    "top5_brier_skill",
    "selected",
]


class SimulationSelectionError(ValueError):
    """Raised when temporal model selection cannot be completed safely."""


def validate_windows(
    validation_date_from: str,
    validation_date_to: str,
    test_date_from: str,
    test_date_to: str,
) -> None:
    if validation_date_from > validation_date_to:
        raise SimulationSelectionError("validation start must not follow validation end")
    if test_date_from > test_date_to:
        raise SimulationSelectionError("test start must not follow test end")
    if validation_date_to >= test_date_from:
        raise SimulationSelectionError(
            "validation must end strictly before the untouched test window starts"
        )


def validated_grid(values: list[float], label: str, allow_zero: bool = False) -> list[float]:
    unique = sorted(set(values))
    if not unique:
        raise SimulationSelectionError(f"{label} grid cannot be empty")
    invalid = [value for value in unique if value < 0 or (value == 0 and not allow_zero)]
    if invalid:
        qualifier = "non-negative" if allow_zero else "positive"
        raise SimulationSelectionError(f"{label} values must be {qualifier}")
    return unique


def brier_skills(metrics: list[dict[str, object]]) -> dict[str, Optional[float]]:
    """Return normalized improvement over each structural baseline."""
    by_target = {str(row["target"]): row for row in metrics}
    skills: dict[str, Optional[float]] = {}
    for target in SELECTION_TARGETS:
        row = by_target.get(target)
        if row is None:
            skills[target] = None
            continue
        baseline = float(row["baseline_brier"])
        if baseline <= 0:
            skills[target] = None
            continue
        skills[target] = (baseline - float(row["model_brier"])) / baseline
    return skills


def mean_available(values: list[Optional[float]]) -> float:
    available = [value for value in values if value is not None]
    if not available:
        raise SimulationSelectionError("no usable validation Brier metrics")
    return sum(available) / len(available)


def selection_row(
    result: dict[str, object],
    half_life_days: float,
    prior_rounds: float,
    variance_prior_rounds: float,
) -> dict[str, object]:
    metrics = result["metrics"]
    events = result["event_summaries"]
    predictions = result["predictions"]
    assert isinstance(metrics, list)
    assert isinstance(events, list)
    assert isinstance(predictions, list)
    skills = brier_skills(metrics)
    objective = mean_available(list(skills.values()))
    return {
        "half_life_days": half_life_days,
        "prior_rounds": prior_rounds,
        "variance_prior_rounds": variance_prior_rounds,
        "validation_events": len(events),
        "validation_prediction_rows": len(predictions),
        "mean_brier_skill": round(objective, 8),
        **{
            f"{target}_brier_skill": (
                "" if skills[target] is None else round(float(skills[target]), 8)
            )
            for target in SELECTION_TARGETS
        },
        "selected": False,
    }


def write_selection_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SELECTION_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def render_selection_report(
    rows: list[dict[str, object]],
    metadata: dict[str, object],
    test_result: dict[str, object],
) -> str:
    selected = next(row for row in rows if row["selected"])
    lines = [
        "# Tournament Simulation Model Selection",
        "",
        "Parameters were selected only on the validation window. The later test",
        "window was evaluated once with the selected configuration.",
        "",
        "## Temporal Split",
        "",
        f"- validation: {metadata['validation_date_from']} through {metadata['validation_date_to']}",
        f"- test: {metadata['test_date_from']} through {metadata['test_date_to']}",
        f"- validation events: {selected['validation_events']}",
        f"- test events: {len(test_result['event_summaries'])}",
        f"- validation simulations per event: {metadata['validation_simulations']}",
        f"- test simulations per event: {metadata['test_simulations']}",
        f"- seed: {metadata['seed']}",
        "",
        "## Selection Objective",
        "",
        "Mean normalized Brier improvement versus the structural baseline across",
        "make-cut, top-20, top-10, and top-5. Targets with a zero baseline Brier",
        "score are omitted. Winner is excluded because it is too sparse for this",
        "small parameter search.",
        "",
        "## Validation Grid",
        "",
        "| Half-life | Mean prior | Variance prior | Mean Brier skill | Selected |",
        "|---:|---:|---:|---:|:---:|",
    ]
    for row in rows:
        lines.append(
            "| {half_life_days} | {prior_rounds} | {variance_prior_rounds} | "
            "{mean_brier_skill:+.4f} | {selected_label} |".format(
                half_life_days=row["half_life_days"],
                prior_rounds=row["prior_rounds"],
                variance_prior_rounds=row["variance_prior_rounds"],
                mean_brier_skill=float(row["mean_brier_skill"]),
                selected_label="yes" if row["selected"] else "",
            )
        )
    lines.extend(
        [
            "",
            "## Untouched Test Metrics",
            "",
            "| Target | Rows | Model Brier | Baseline Brier | Improvement |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    metrics = test_result["metrics"]
    assert isinstance(metrics, list)
    for row in metrics:
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
            "This is performance-model validation, not evidence of a betting edge.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def run_simulation_model_selection(
    canonical_dir: Path,
    round_performance_path: Path,
    output_dir: Path,
    validation_date_from: str,
    validation_date_to: str,
    test_date_from: str,
    test_date_to: str,
    half_life_grid: list[float],
    prior_rounds_grid: list[float],
    variance_prior_rounds_grid: list[float],
    max_validation_events: int = 0,
    max_test_events: int = 0,
    validation_simulations: int = 500,
    test_simulations: int = 2000,
    seed: int = 20260729,
    cut_size: int = 65,
) -> dict[str, object]:
    validate_windows(
        validation_date_from,
        validation_date_to,
        test_date_from,
        test_date_to,
    )
    if validation_simulations <= 0 or test_simulations <= 0:
        raise SimulationSelectionError("simulation counts must be positive")
    half_lives = validated_grid(half_life_grid, "half-life")
    priors = validated_grid(prior_rounds_grid, "prior-rounds", allow_zero=True)
    variance_priors = validated_grid(
        variance_prior_rounds_grid,
        "variance-prior-rounds",
        allow_zero=True,
    )
    inputs = prepare_backtest_inputs(canonical_dir, round_performance_path)

    candidates: list[tuple[dict[str, object], dict[str, object]]] = []
    for half_life, prior, variance_prior in product(
        half_lives,
        priors,
        variance_priors,
    ):
        validation_result = evaluate_simulation_backtest(
            inputs,
            date_from=validation_date_from,
            date_to=validation_date_to,
            max_events=max_validation_events,
            simulations=validation_simulations,
            seed=seed,
            cut_size=cut_size,
            half_life_days=half_life,
            prior_rounds=prior,
            variance_prior_rounds=variance_prior,
        )
        row = selection_row(validation_result, half_life, prior, variance_prior)
        candidates.append((row, validation_result))

    selected_pair = max(
        candidates,
        key=lambda pair: (
            float(pair[0]["mean_brier_skill"]),
            -float(pair[0]["half_life_days"]),
            -float(pair[0]["prior_rounds"]),
            -float(pair[0]["variance_prior_rounds"]),
        ),
    )
    selected_row, selected_validation_result = selected_pair
    selected_row["selected"] = True
    rows = [pair[0] for pair in candidates]
    rows.sort(
        key=lambda row: (
            -float(row["mean_brier_skill"]),
            float(row["half_life_days"]),
            float(row["prior_rounds"]),
            float(row["variance_prior_rounds"]),
        )
    )

    test_result = evaluate_simulation_backtest(
        inputs,
        date_from=test_date_from,
        date_to=test_date_to,
        max_events=max_test_events,
        simulations=test_simulations,
        seed=seed + 1_000_000,
        cut_size=cut_size,
        half_life_days=float(selected_row["half_life_days"]),
        prior_rounds=float(selected_row["prior_rounds"]),
        variance_prior_rounds=float(selected_row["variance_prior_rounds"]),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    selection_path = output_dir / "selection.csv"
    metadata_path = output_dir / "selected_parameters.json"
    report_path = output_dir / "report.md"
    write_selection_csv(selection_path, rows)
    validation_outputs = write_simulation_backtest_outputs(
        selected_validation_result,
        output_dir / "selected_validation",
        validation_simulations,
        seed,
    )
    test_outputs = write_simulation_backtest_outputs(
        test_result,
        output_dir / "untouched_test",
        test_simulations,
        seed + 1_000_000,
    )
    metadata = {
        "validation_date_from": validation_date_from,
        "validation_date_to": validation_date_to,
        "test_date_from": test_date_from,
        "test_date_to": test_date_to,
        "max_validation_events": max_validation_events,
        "max_test_events": max_test_events,
        "validation_simulations": validation_simulations,
        "test_simulations": test_simulations,
        "seed": seed,
        "cut_size": cut_size,
        "selection_targets": list(SELECTION_TARGETS),
        "objective": "mean_normalized_brier_improvement",
        "selected": {
            "half_life_days": selected_row["half_life_days"],
            "prior_rounds": selected_row["prior_rounds"],
            "variance_prior_rounds": selected_row["variance_prior_rounds"],
            "validation_mean_brier_skill": selected_row["mean_brier_skill"],
        },
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(
        render_selection_report(rows, metadata, test_result),
        encoding="utf-8",
    )
    return {
        "selection_rows": rows,
        "selected": selected_row,
        "validation": validation_outputs,
        "test": test_outputs,
        "selection_path": selection_path,
        "metadata_path": metadata_path,
        "report_path": report_path,
    }


def comma_separated_floats(value: str) -> list[float]:
    try:
        return [float(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated numbers") from exc


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="simulation-model-selection")
    parser.add_argument("--canonical-dir", required=True, type=Path)
    parser.add_argument("--round-performance", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--validation-date-from", required=True)
    parser.add_argument("--validation-date-to", required=True)
    parser.add_argument("--test-date-from", required=True)
    parser.add_argument("--test-date-to", required=True)
    parser.add_argument("--half-life-grid", type=comma_separated_floats, default=[90, 180, 365])
    parser.add_argument("--prior-rounds-grid", type=comma_separated_floats, default=[8, 20, 40])
    parser.add_argument(
        "--variance-prior-rounds-grid",
        type=comma_separated_floats,
        default=[20],
    )
    parser.add_argument("--max-validation-events", type=int, default=0)
    parser.add_argument("--max-test-events", type=int, default=0)
    parser.add_argument("--validation-simulations", type=int, default=500)
    parser.add_argument("--test-simulations", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--cut-size", type=int, default=65)
    args = parser.parse_args(argv)
    result = run_simulation_model_selection(
        args.canonical_dir,
        args.round_performance,
        args.output_dir,
        args.validation_date_from,
        args.validation_date_to,
        args.test_date_from,
        args.test_date_to,
        args.half_life_grid,
        args.prior_rounds_grid,
        args.variance_prior_rounds_grid,
        max_validation_events=args.max_validation_events,
        max_test_events=args.max_test_events,
        validation_simulations=args.validation_simulations,
        test_simulations=args.test_simulations,
        seed=args.seed,
        cut_size=args.cut_size,
    )
    print(f"simulation_selection={result['selection_path']}")
    print(f"simulation_selection_parameters={result['metadata_path']}")
    print(f"simulation_selection_report={result['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
