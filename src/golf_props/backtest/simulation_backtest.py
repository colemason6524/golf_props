"""Walk-forward evaluation for the round-strength tournament simulator."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from golf_props.features.player_event import (
    parse_bool,
    parse_int,
    primary_course_by_event,
    target_at_or_better,
)
from golf_props.models.round_strength import (
    PreparedRoundHistory,
    estimate_strength_rows,
    prepare_round_history,
)
from golf_props.models.tournament_simulator import simulate_tournament_rows

TARGET_TO_PROBABILITY = {
    "make_cut": "make_cut_prob",
    "top20": "top20_prob",
    "top10": "top10_prob",
    "top5": "top5_prob",
    "winner": "winner_prob",
}

PREDICTION_COLUMNS = [
    "event_id",
    "event_name",
    "event_date",
    "target",
    "player_id",
    "player_name",
    "actual",
    "model_prob",
    "baseline_prob",
    "rounds_used",
]

METRIC_COLUMNS = [
    "target",
    "events",
    "rows",
    "actual_rate",
    "avg_model_prob",
    "avg_baseline_prob",
    "model_brier",
    "baseline_brier",
    "model_log_loss",
    "baseline_log_loss",
    "brier_improvement",
]

CALIBRATION_COLUMNS = [
    "target",
    "probability_bucket",
    "rows",
    "avg_model_prob",
    "actual_rate",
]


class SimulationBacktestError(ValueError):
    """Raised when a simulation backtest cannot be run."""


@dataclass(frozen=True)
class SimulationBacktestInputs:
    """Canonical inputs and reusable indexes for repeated evaluations."""

    events: list[dict[str, str]]
    players: list[dict[str, str]]
    results: list[dict[str, str]]
    round_rows: list[dict[str, str]]
    player_by_id: dict[str, dict[str, str]]
    results_by_event: dict[str, list[dict[str, str]]]
    course_by_event: dict[str, str]
    prepared_history: PreparedRoundHistory


StrengthTransform = Callable[
    [list[dict[str, object]], dict[str, str]],
    list[dict[str, object]],
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SimulationBacktestError(f"missing input file: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(
    path: Path,
    columns: list[str],
    rows: list[dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def actual_targets(result: dict[str, str]) -> dict[str, Optional[int]]:
    finish_position = parse_int(result.get("finish_position", ""))
    made_cut = parse_bool(result.get("made_cut", ""))
    withdrawn = parse_bool(result.get("withdrawn", "")) or False
    disqualified = parse_bool(result.get("disqualified", "")) or False

    def placement(threshold: int) -> Optional[int]:
        value = target_at_or_better(
            finish_position,
            threshold,
            made_cut,
            withdrawn,
            disqualified,
        )
        return None if value is None else int(value)

    return {
        "make_cut": (
            None
            if made_cut is None or withdrawn or disqualified
            else int(made_cut)
        ),
        "top20": placement(20),
        "top10": placement(10),
        "top5": placement(5),
        "winner": placement(1),
    }


def structural_baseline(target: str, field_size: int, cut_size: int) -> float:
    if target == "make_cut":
        return min(cut_size / field_size, 1.0)
    slots = {"top20": 20, "top10": 10, "top5": 5, "winner": 1}[target]
    return min(slots / field_size, 1.0)


def clip_probability(value: float) -> float:
    return min(max(value, 1e-6), 1 - 1e-6)


def brier(rows: list[dict[str, object]], probability_column: str) -> float:
    return sum(
        (float(row[probability_column]) - int(row["actual"])) ** 2 for row in rows
    ) / len(rows)


def log_loss(rows: list[dict[str, object]], probability_column: str) -> float:
    total = 0.0
    for row in rows:
        actual = int(row["actual"])
        probability = clip_probability(float(row[probability_column]))
        total -= actual * math.log(probability) + (1 - actual) * math.log(
            1 - probability
        )
    return total / len(rows)


def metric_rows(predictions: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in predictions:
        grouped[str(row["target"])].append(row)
    output = []
    for target in TARGET_TO_PROBABILITY:
        rows = grouped.get(target, [])
        if not rows:
            continue
        model_brier = brier(rows, "model_prob")
        baseline_brier = brier(rows, "baseline_prob")
        output.append(
            {
                "target": target,
                "events": len({row["event_id"] for row in rows}),
                "rows": len(rows),
                "actual_rate": round(
                    sum(int(row["actual"]) for row in rows) / len(rows),
                    6,
                ),
                "avg_model_prob": round(
                    sum(float(row["model_prob"]) for row in rows) / len(rows),
                    6,
                ),
                "avg_baseline_prob": round(
                    sum(float(row["baseline_prob"]) for row in rows) / len(rows),
                    6,
                ),
                "model_brier": round(model_brier, 6),
                "baseline_brier": round(baseline_brier, 6),
                "model_log_loss": round(log_loss(rows, "model_prob"), 6),
                "baseline_log_loss": round(log_loss(rows, "baseline_prob"), 6),
                "brier_improvement": round(baseline_brier - model_brier, 6),
            }
        )
    return output


def calibration_rows(
    predictions: list[dict[str, object]],
) -> list[dict[str, object]]:
    buckets: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in predictions:
        probability = float(row["model_prob"])
        bucket_start = min(int(probability * 10) * 10, 90)
        bucket = f"{bucket_start:02d}-{bucket_start + 10:02d}"
        buckets[(str(row["target"]), bucket)].append(row)
    output = []
    for (target, bucket), rows in sorted(buckets.items()):
        output.append(
            {
                "target": target,
                "probability_bucket": bucket,
                "rows": len(rows),
                "avg_model_prob": round(
                    sum(float(row["model_prob"]) for row in rows) / len(rows),
                    6,
                ),
                "actual_rate": round(
                    sum(int(row["actual"]) for row in rows) / len(rows),
                    6,
                ),
            }
        )
    return output


def selected_events(
    events: list[dict[str, str]],
    result_event_ids: set[str],
    date_from: Optional[str],
    date_to: Optional[str],
    max_events: int,
) -> list[dict[str, str]]:
    selected = []
    for event in events:
        event_date = event.get("date_start", "")
        if not event_date or event["event_id"] not in result_event_ids:
            continue
        if date_from and event_date < date_from:
            continue
        if date_to and event_date > date_to:
            continue
        if event.get("format") not in {"", "stroke_play"}:
            continue
        selected.append(event)
    selected.sort(key=lambda row: (row["date_start"], row["event_id"]))
    if max_events > 0:
        selected = selected[-max_events:]
    return selected


def prepare_backtest_inputs(
    canonical_dir: Path,
    round_performance_path: Path,
) -> SimulationBacktestInputs:
    """Read canonical data and build indexes once for parameter searches."""
    events = read_csv(canonical_dir / "events.csv")
    players = read_csv(canonical_dir / "players.csv")
    results = read_csv(canonical_dir / "player_event_results.csv")
    event_courses = read_csv(canonical_dir / "event_courses.csv")
    round_rows = read_csv(round_performance_path)
    player_by_id = {row["player_id"]: row for row in players}
    results_by_event: dict[str, list[dict[str, str]]] = defaultdict(list)
    for result in results:
        results_by_event[result["event_id"]].append(result)
    return SimulationBacktestInputs(
        events=events,
        players=players,
        results=results,
        round_rows=round_rows,
        player_by_id=player_by_id,
        results_by_event=dict(results_by_event),
        course_by_event=primary_course_by_event(event_courses),
        prepared_history=prepare_round_history(round_rows),
    )


def evaluate_simulation_backtest(
    inputs: SimulationBacktestInputs,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    max_events: int = 10,
    simulations: int = 2000,
    seed: int = 20260729,
    cut_size: int = 65,
    half_life_days: float = 180.0,
    prior_rounds: float = 20.0,
    variance_prior_rounds: float = 20.0,
    strength_transform: Optional[StrengthTransform] = None,
) -> dict[str, object]:
    """Evaluate one parameter set without writing intermediate artifacts."""
    events_to_test = selected_events(
        inputs.events,
        set(inputs.results_by_event),
        date_from,
        date_to,
        max_events,
    )
    if not events_to_test:
        raise SimulationBacktestError("no eligible events selected")

    predictions: list[dict[str, object]] = []
    event_summaries = []
    for event_index, event in enumerate(events_to_test):
        event_results = inputs.results_by_event[event["event_id"]]
        field_rows = []
        for result in event_results:
            player = inputs.player_by_id.get(result["player_id"])
            if player is None:
                continue
            field_rows.append(
                {
                    "player_id": result["player_id"],
                    "player_name": player["player_name"],
                    "entry_status": "historical",
                }
            )
        if len(field_rows) < 2:
            continue
        strengths, strength_summary = estimate_strength_rows(
            inputs.round_rows,
            field_rows,
            event["date_start"],
            half_life_days=half_life_days,
            prior_rounds=prior_rounds,
            variance_prior_rounds=variance_prior_rounds,
            prepared_history=inputs.prepared_history,
        )
        if strength_transform is not None:
            strengths = strength_transform(strengths, event)
        simulated, simulation_summary = simulate_tournament_rows(
            strengths,
            event["event_name"],
            event["date_start"],
            simulations=simulations,
            seed=seed + event_index,
            cut_size=cut_size,
        )
        simulated_by_id = {row["player_id"]: row for row in simulated}
        event_field_size = len(field_rows)
        for result in event_results:
            simulation = simulated_by_id.get(result["player_id"])
            player = inputs.player_by_id.get(result["player_id"])
            if simulation is None or player is None:
                continue
            targets = actual_targets(result)
            for target, actual in targets.items():
                if actual is None:
                    continue
                predictions.append(
                    {
                        "event_id": event["event_id"],
                        "event_name": event["event_name"],
                        "event_date": event["date_start"],
                        "target": target,
                        "player_id": result["player_id"],
                        "player_name": player["player_name"],
                        "actual": actual,
                        "model_prob": simulation[TARGET_TO_PROBABILITY[target]],
                        "baseline_prob": round(
                            structural_baseline(target, event_field_size, cut_size),
                            6,
                        ),
                        "rounds_used": simulation.get("rounds_used", ""),
                    }
                )
        event_summaries.append(
            {
                "event_id": event["event_id"],
                "event_name": event["event_name"],
                "event_date": event["date_start"],
                "field_size": event_field_size,
                "eligible_historical_rounds": strength_summary[
                    "eligible_historical_rounds"
                ],
                "average_players_making_cut": simulation_summary[
                    "average_players_making_cut"
                ],
                "course_history_players": sum(
                    float(row.get("course_effective_rounds") or 0) > 0
                    for row in strengths
                ),
                "average_absolute_course_adjustment": round(
                    sum(abs(float(row.get("course_adjustment") or 0)) for row in strengths)
                    / len(strengths),
                    6,
                ),
            }
        )

    return {
        "events": events_to_test,
        "predictions": predictions,
        "metrics": metric_rows(predictions),
        "calibration": calibration_rows(predictions),
        "event_summaries": event_summaries,
        "parameters": {
            "half_life_days": half_life_days,
            "prior_rounds": prior_rounds,
            "variance_prior_rounds": variance_prior_rounds,
            "cut_size": cut_size,
        },
    }


def write_simulation_backtest_outputs(
    result: dict[str, object],
    output_dir: Path,
    simulations: int,
    seed: int,
) -> dict[str, object]:
    """Persist an in-memory backtest result and return its artifact paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = output_dir / "predictions.csv"
    metrics_path = output_dir / "metrics.csv"
    calibration_path = output_dir / "calibration.csv"
    report_path = output_dir / "report.md"
    predictions = result["predictions"]
    metrics = result["metrics"]
    calibration = result["calibration"]
    events = result["events"]
    event_summaries = result["event_summaries"]
    assert isinstance(predictions, list)
    assert isinstance(metrics, list)
    assert isinstance(calibration, list)
    assert isinstance(events, list)
    assert isinstance(event_summaries, list)
    write_csv(predictions_path, PREDICTION_COLUMNS, predictions)
    write_csv(metrics_path, METRIC_COLUMNS, metrics)
    write_csv(calibration_path, CALIBRATION_COLUMNS, calibration)
    report_path.write_text(
        render_report(
            events,
            predictions,
            metrics,
            simulations,
            seed,
            event_summaries,
            parameters=result.get("parameters"),
        ),
        encoding="utf-8",
    )
    return {
        **result,
        "predictions_path": predictions_path,
        "metrics_path": metrics_path,
        "calibration_path": calibration_path,
        "report_path": report_path,
    }


def run_simulation_backtest(
    canonical_dir: Path,
    round_performance_path: Path,
    output_dir: Path,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    max_events: int = 10,
    simulations: int = 2000,
    seed: int = 20260729,
    cut_size: int = 65,
    half_life_days: float = 180.0,
    prior_rounds: float = 20.0,
    variance_prior_rounds: float = 20.0,
) -> dict[str, object]:
    inputs = prepare_backtest_inputs(canonical_dir, round_performance_path)
    result = evaluate_simulation_backtest(
        inputs,
        date_from,
        date_to,
        max_events,
        simulations,
        seed,
        cut_size,
        half_life_days,
        prior_rounds,
        variance_prior_rounds,
    )
    return write_simulation_backtest_outputs(result, output_dir, simulations, seed)


def render_report(
    events: list[dict[str, str]],
    predictions: list[dict[str, object]],
    metrics: list[dict[str, object]],
    simulations: int,
    seed: int,
    event_summaries: list[dict[str, object]],
    parameters: Optional[object] = None,
) -> str:
    lines = [
        "# Walk-Forward Tournament Simulation Backtest",
        "",
        f"- selected_events: {len(events)}",
        f"- completed_event_simulations: {len(event_summaries)}",
        f"- prediction_rows: {len(predictions)}",
        f"- simulations_per_event: {simulations}",
        f"- base_seed: {seed}",
        "",
        "## Metrics",
        "",
        "| Target | Rows | Actual | Model | Baseline | Model Brier | Baseline Brier | Improvement |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    if isinstance(parameters, dict):
        lines[7:7] = [
            f"- half_life_days: {parameters.get('half_life_days')}",
            f"- prior_rounds: {parameters.get('prior_rounds')}",
            f"- variance_prior_rounds: {parameters.get('variance_prior_rounds')}",
        ]
    for row in metrics:
        lines.append(
            "| {target} | {rows} | {actual:.3f} | {model:.3f} | "
            "{baseline:.3f} | {model_brier:.4f} | {baseline_brier:.4f} | "
            "{improvement:+.4f} |".format(
                target=row["target"],
                rows=row["rows"],
                actual=float(row["actual_rate"]),
                model=float(row["avg_model_prob"]),
                baseline=float(row["avg_baseline_prob"]),
                model_brier=float(row["model_brier"]),
                baseline_brier=float(row["baseline_brier"]),
                improvement=float(row["brier_improvement"]),
            )
        )
    lines.extend(["", "Positive Brier improvement means the simulator beat the structural baseline."])
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="simulation-backtest")
    parser.add_argument("--canonical-dir", required=True, type=Path)
    parser.add_argument("--round-performance", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")
    parser.add_argument("--max-events", type=int, default=10)
    parser.add_argument("--simulations", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--cut-size", type=int, default=65)
    parser.add_argument("--half-life-days", type=float, default=180.0)
    parser.add_argument("--prior-rounds", type=float, default=20.0)
    parser.add_argument("--variance-prior-rounds", type=float, default=20.0)
    args = parser.parse_args(argv)

    result = run_simulation_backtest(
        args.canonical_dir,
        args.round_performance,
        args.output_dir,
        date_from=args.date_from,
        date_to=args.date_to,
        max_events=args.max_events,
        simulations=args.simulations,
        seed=args.seed,
        cut_size=args.cut_size,
        half_life_days=args.half_life_days,
        prior_rounds=args.prior_rounds,
        variance_prior_rounds=args.variance_prior_rounds,
    )
    print(f"simulation_backtest_events={len(result['event_summaries'])}")
    print(f"simulation_backtest_predictions={result['predictions_path']}")
    print(f"simulation_backtest_metrics={result['metrics_path']}")
    print(f"simulation_backtest_report={result['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
