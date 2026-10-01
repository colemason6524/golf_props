"""Grade an immutable prospective forecast against preserved CBS results."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from golf_props.backtest.forecast_archive import verify_forecast_archive
from golf_props.normalization.cbs_results import parse_finish_position, parse_leaderboard_rows

GRADED_TARGETS = ("top20", "top10", "top5", "winner")
TARGET_SLOTS = {"top20": 20, "top10": 10, "top5": 5, "winner": 1}
TARGET_PROBABILITY = {target: f"{target}_prob" for target in GRADED_TARGETS}
GRADED_PREDICTION_COLUMNS = [
    "event_name",
    "event_date",
    "target",
    "player_id",
    "player_name",
    "finish_text",
    "finish_position",
    "actual",
    "model_prob",
    "baseline_prob",
]
METRIC_COLUMNS = [
    "target",
    "forecast_players",
    "graded_players",
    "excluded_players",
    "actual_count",
    "actual_rate",
    "expected_count",
    "avg_model_prob",
    "calibration_gap",
    "model_brier",
    "baseline_brier",
    "brier_improvement",
    "rolling_model_brier",
    "brier_vs_rolling",
    "model_log_loss",
    "baseline_log_loss",
    "rolling_model_log_loss",
    "log_loss_vs_rolling",
]


class ForecastGradingError(ValueError):
    """Raised when a prospective forecast cannot be graded safely."""


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise ForecastGradingError(f"missing input file: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _name_key(value: str) -> str:
    return " ".join(value.casefold().split())


def _clipped(value: float) -> float:
    return min(max(value, 1e-6), 1 - 1e-6)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _metric_rows(
    rows: list[dict[str, object]],
    forecast_players: int,
    excluded_players: int,
    rolling_by_target: dict[str, dict[str, str]],
) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["target"])].append(row)

    output = []
    for target in GRADED_TARGETS:
        target_rows = grouped[target]
        probabilities = [float(row["model_prob"]) for row in target_rows]
        baselines = [float(row["baseline_prob"]) for row in target_rows]
        actuals = [int(row["actual"]) for row in target_rows]
        model_brier = _mean([(probability - actual) ** 2 for probability, actual in zip(probabilities, actuals)])
        baseline_brier = _mean([(probability - actual) ** 2 for probability, actual in zip(baselines, actuals)])
        model_log_loss = _mean(
            [
                -(actual * math.log(_clipped(probability)) + (1 - actual) * math.log(1 - _clipped(probability)))
                for probability, actual in zip(probabilities, actuals)
            ]
        )
        baseline_log_loss = _mean(
            [
                -(actual * math.log(_clipped(probability)) + (1 - actual) * math.log(1 - _clipped(probability)))
                for probability, actual in zip(baselines, actuals)
            ]
        )
        rolling = rolling_by_target.get(target)
        if rolling is None:
            raise ForecastGradingError(f"rolling metrics missing target: {target}")
        rolling_brier = float(rolling["model_brier"])
        rolling_log_loss = float(rolling["model_log_loss"])
        actual_rate = _mean([float(value) for value in actuals])
        avg_probability = _mean(probabilities)
        output.append(
            {
                "target": target,
                "forecast_players": forecast_players,
                "graded_players": len(target_rows),
                "excluded_players": excluded_players,
                "actual_count": sum(actuals),
                "actual_rate": round(actual_rate, 6),
                "expected_count": round(sum(probabilities), 6),
                "avg_model_prob": round(avg_probability, 6),
                "calibration_gap": round(actual_rate - avg_probability, 6),
                "model_brier": round(model_brier, 6),
                "baseline_brier": round(baseline_brier, 6),
                "brier_improvement": round(baseline_brier - model_brier, 6),
                "rolling_model_brier": round(rolling_brier, 6),
                "brier_vs_rolling": round(model_brier - rolling_brier, 6),
                "model_log_loss": round(model_log_loss, 6),
                "baseline_log_loss": round(baseline_log_loss, 6),
                "rolling_model_log_loss": round(rolling_log_loss, 6),
                "log_loss_vs_rolling": round(model_log_loss - rolling_log_loss, 6),
            }
        )
    return output


def _report(
    event_name: str,
    metrics: list[dict[str, object]],
    excluded_names: list[str],
    winner_name: str,
    predicted_winner_name: str,
    results_url: str,
) -> str:
    lines = [
        f"# {event_name} Prospective Forecast Grade",
        "",
        "## Scope",
        "",
        "- Classification: genuinely prospective frozen forecast.",
        "- Graded targets: top-20, top-10, top-5, winner.",
        "- `make_cut` excluded because this was a no-cut event.",
        f"- Results source: CBS Sports ({results_url or 'preserved raw leaderboard page'}).",
        f"- Actual winner: {winner_name}.",
        f"- Highest forecast winner probability: {predicted_winner_name}.",
        f"- Placement rows excluded under the established withdrawal rule: {', '.join(excluded_names) if excluded_names else 'none'}.",
        "",
        "## Metrics",
        "",
        "| Target | Graded | Actual | Expected | Brier | Structural | Improvement | Rolling Brier | Log loss | Rolling log loss |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in metrics:
        lines.append(
            "| {target} | {graded_players} | {actual_count} | {expected_count:.3f} | "
            "{model_brier:.4f} | {baseline_brier:.4f} | {brier_improvement:+.4f} | "
            "{rolling_model_brier:.4f} | {model_log_loss:.4f} | {rolling_model_log_loss:.4f} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The sign of `Improvement` is structural-baseline Brier minus model Brier, so positive is better. "
            "`Rolling Brier` and `Rolling log loss` are historical aggregate expectations, not thresholds that one event must beat.",
            "",
            f"This single {metrics[0]['graded_players']}-player graded event is too small to estimate a stable calibration curve or justify retuning. "
            "The frozen 365/8/20 incumbent remains unchanged; accumulate additional genuinely prospective events before drawing model-level conclusions.",
            "",
        ]
    )
    return "\n".join(lines)


def grade_forecast(
    archive_dir: Path,
    results_page: Path,
    rolling_metrics_path: Path,
    output_dir: Path,
    results_url: str = "",
    created_at: Optional[datetime] = None,
) -> dict[str, Any]:
    """Verify and grade one prospective archive without modifying it."""
    verification = verify_forecast_archive(archive_dir)
    if not verification["verified"]:
        raise ForecastGradingError(
            "forecast archive verification failed: " + ", ".join(verification["problems"])
        )
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ForecastGradingError(f"grading output directory is not empty: {output_dir}")

    run_manifest = json.loads((archive_dir / "run_manifest.json").read_text(encoding="utf-8"))
    if run_manifest.get("eligibility", {}).get("classification") != "prospective_forecast":
        raise ForecastGradingError("archive is not classified as a prospective forecast")
    predictions = _read_csv(archive_dir / "predictions.csv")
    if not predictions:
        raise ForecastGradingError("forecast contains no predictions")
    forecast_by_name = {_name_key(row["player_name"]): row for row in predictions}
    if len(forecast_by_name) != len(predictions):
        raise ForecastGradingError("forecast contains duplicate normalized player names")

    result_rows = parse_leaderboard_rows(results_page.read_text(encoding="utf-8"))
    results_by_name = {_name_key(str(row["player_name"])): row for row in result_rows}
    if len(results_by_name) != len(result_rows):
        raise ForecastGradingError("results contain duplicate normalized player names")
    missing_results = sorted(set(forecast_by_name) - set(results_by_name))
    unexpected_results = sorted(set(results_by_name) - set(forecast_by_name))
    if missing_results or unexpected_results:
        raise ForecastGradingError(
            f"forecast/results field mismatch; missing={missing_results}, unexpected={unexpected_results}"
        )

    forecast_players = len(predictions)
    baseline_by_target = {
        target: min(TARGET_SLOTS[target] / forecast_players, 1.0)
        for target in GRADED_TARGETS
    }
    graded_rows = []
    excluded_names = []
    for prediction in predictions:
        result = results_by_name[_name_key(prediction["player_name"])]
        finish_text = str(result["position"])
        finish_position = parse_finish_position(finish_text)
        if finish_text.strip().upper() in {"WD", "DNS", "DQ"}:
            excluded_names.append(prediction["player_name"])
            continue
        if finish_position is None:
            raise ForecastGradingError(
                f"ungradable finish for {prediction['player_name']}: {finish_text}"
            )
        for target in GRADED_TARGETS:
            graded_rows.append(
                {
                    "event_name": prediction["event_name"],
                    "event_date": prediction["event_date"],
                    "target": target,
                    "player_id": prediction["player_id"],
                    "player_name": prediction["player_name"],
                    "finish_text": finish_text,
                    "finish_position": finish_position,
                    "actual": int(finish_position <= TARGET_SLOTS[target]),
                    "model_prob": prediction[TARGET_PROBABILITY[target]],
                    "baseline_prob": round(baseline_by_target[target], 6),
                }
            )

    rolling_rows = _read_csv(rolling_metrics_path)
    rolling_by_target = {row["target"]: row for row in rolling_rows}
    metrics = _metric_rows(
        graded_rows,
        forecast_players,
        len(excluded_names),
        rolling_by_target,
    )
    winners = [row for row in result_rows if parse_finish_position(str(row["position"])) == 1]
    if len(winners) != 1:
        raise ForecastGradingError(f"expected exactly one winner, found {len(winners)}")
    predicted_winner = max(predictions, key=lambda row: float(row["winner_prob"]))

    output_dir.mkdir(parents=True, exist_ok=True)
    graded_path = output_dir / "graded_predictions.csv"
    metrics_path = output_dir / "metrics.csv"
    report_path = output_dir / "report.md"
    manifest_path = output_dir / "grading_manifest.json"
    _write_csv(graded_path, GRADED_PREDICTION_COLUMNS, graded_rows)
    _write_csv(metrics_path, METRIC_COLUMNS, metrics)
    report_path.write_text(
        _report(
            predictions[0]["event_name"],
            metrics,
            excluded_names,
            str(winners[0]["player_name"]),
            predicted_winner["player_name"],
            results_url,
        ),
        encoding="utf-8",
    )
    timestamp = created_at or datetime.now(timezone.utc)
    manifest = {
        "schema_version": 1,
        "created_at_utc": timestamp.astimezone(timezone.utc).isoformat(),
        "event_name": predictions[0]["event_name"],
        "forecast_classification": "prospective_forecast",
        "graded_targets": list(GRADED_TARGETS),
        "excluded_targets": ["make_cut"],
        "forecast_players": forecast_players,
        "graded_players_per_target": forecast_players - len(excluded_names),
        "excluded_players": excluded_names,
        "results_source": {"organization": "CBS Sports", "url": results_url},
        "input_sha256": {
            "archive_manifest": _sha256(archive_dir / "archive_manifest.json"),
            "predictions": _sha256(archive_dir / "predictions.csv"),
            "results_page": _sha256(results_page),
            "rolling_metrics": _sha256(rolling_metrics_path),
        },
        "artifact_sha256": {
            "graded_predictions": _sha256(graded_path),
            "metrics": _sha256(metrics_path),
            "report": _sha256(report_path),
        },
        "archive_verification": verification,
        "frozen_parameters_changed": False,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "graded_predictions_path": graded_path,
        "metrics_path": metrics_path,
        "report_path": report_path,
        "manifest_path": manifest_path,
        "metrics": metrics,
        "manifest": manifest,
    }
