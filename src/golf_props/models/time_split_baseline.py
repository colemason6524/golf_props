"""Time-split baseline reports for player-event golf prop targets."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Optional

TARGET_COLUMNS = [
    "target_make_cut",
    "target_top20",
    "target_top10",
    "target_top5",
]

FEATURE_COLUMNS = [
    "field_size",
    "prior_starts",
    "days_since_last_start",
    "recent_made_cut_rate",
    "recent_top20_rate",
    "recent_top10_rate",
    "recent_top5_rate",
    "recent_avg_finish",
    "recent_avg_score_to_par",
    "course_starts",
    "course_made_cut_rate",
    "course_top20_rate",
    "course_avg_finish",
]

PREDICTION_COLUMNS = [
    "target",
    "event_id",
    "event_name",
    "event_date_start",
    "season",
    "player_id",
    "player_name",
    "course_id",
    "course_name",
    "actual",
    "base_rate_prob",
    "player_rolling_prob",
    "model_prob",
    "model_type",
]

METRIC_COLUMNS = [
    "target",
    "test_event_id",
    "test_event_name",
    "test_event_date",
    "train_rows",
    "test_rows",
    "train_positive_rate",
    "actual_rate",
    "avg_base_rate_prob",
    "avg_player_rolling_prob",
    "avg_model_prob",
    "base_rate_brier",
    "player_rolling_brier",
    "model_brier",
    "base_rate_log_loss",
    "player_rolling_log_loss",
    "model_log_loss",
    "model_type",
]

CALIBRATION_COLUMNS = [
    "target",
    "model_type",
    "probability_bucket",
    "rows",
    "avg_predicted",
    "actual_rate",
]


class BaselineError(ValueError):
    """Raised when baseline inputs are invalid."""


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise BaselineError(f"missing features file: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_target(value: str) -> Optional[int]:
    if value == "":
        return None
    if value == "True":
        return 1
    if value == "False":
        return 0
    raise BaselineError(f"invalid target value: {value}")


def parse_float(value: str) -> Optional[float]:
    if value == "":
        return None
    return float(value)


def clip_probability(probability: float) -> float:
    return min(max(probability, 1e-6), 1 - 1e-6)


def brier_score(actuals: list[int], probabilities: list[float]) -> float:
    return sum((prob - actual) ** 2 for actual, prob in zip(actuals, probabilities)) / len(actuals)


def log_loss(actuals: list[int], probabilities: list[float]) -> float:
    total = 0.0
    for actual, probability in zip(actuals, probabilities):
        probability = clip_probability(probability)
        total += actual * math.log(probability) + (1 - actual) * math.log(1 - probability)
    return -total / len(actuals)


def average(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def format_float(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value, 6)


def eligible_rows(rows: list[dict[str, str]], target: str) -> list[dict[str, object]]:
    eligible = []
    for row in rows:
        actual = parse_target(row.get(target, ""))
        if actual is None:
            continue
        eligible.append({**row, "_actual": actual})
    return eligible


def event_dates(rows: list[dict[str, object]]) -> list[str]:
    return sorted({str(row["event_date_start"]) for row in rows})


def base_rate(train_rows: list[dict[str, object]]) -> float:
    actuals = [int(row["_actual"]) for row in train_rows]
    return sum(actuals) / len(actuals)


def can_fit_logistic(train_rows: list[dict[str, object]], min_train_rows: int) -> bool:
    if len(train_rows) < min_train_rows:
        return False
    classes = {row["_actual"] for row in train_rows}
    return classes == {0, 1}


def fit_logistic_predict(
    train_rows: list[dict[str, object]],
    test_rows: list[dict[str, object]],
    min_train_rows: int,
    enable_logistic: bool,
) -> tuple[str, Optional[list[float]]]:
    if not enable_logistic:
        return "base_rate", None
    if not can_fit_logistic(train_rows, min_train_rows):
        return "base_rate", None

    try:
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        return "base_rate", None

    train_x = feature_matrix(train_rows)
    train_y = [int(row["_actual"]) for row in train_rows]
    test_x = feature_matrix(test_rows)
    pipeline = make_pipeline(
        SimpleImputer(strategy="median"),
        StandardScaler(),
        LogisticRegression(max_iter=1000),
    )
    pipeline.fit(train_x, train_y)
    probabilities = [float(prob) for prob in pipeline.predict_proba(test_x)[:, 1]]
    return "logistic_regression", probabilities


def rolling_feature_for_target(target: str) -> str:
    return {
        "target_make_cut": "recent_made_cut_rate",
        "target_top20": "recent_top20_rate",
        "target_top10": "recent_top10_rate",
        "target_top5": "recent_top5_rate",
    }[target]


def player_rolling_probs(
    target: str,
    test_rows: list[dict[str, object]],
    fallback_prob: float,
    min_prior_starts: int,
) -> list[float]:
    feature = rolling_feature_for_target(target)
    probabilities = []
    for row in test_rows:
        prior_starts = parse_float(str(row.get("prior_starts", ""))) or 0.0
        rolling_prob = parse_float(str(row.get(feature, "")))
        if prior_starts >= min_prior_starts and rolling_prob is not None:
            probabilities.append(rolling_prob)
        else:
            probabilities.append(fallback_prob)
    return probabilities


def feature_matrix(rows: list[dict[str, object]]) -> list[list[Optional[float]]]:
    return [[parse_float(str(row.get(column, ""))) for column in FEATURE_COLUMNS] for row in rows]


def build_metrics_row(
    target: str,
    test_event_id: str,
    test_event_name: str,
    test_event_date: str,
    train_row_count: int,
    train_positive_rate: float,
    test_rows: list[dict[str, object]],
    base_probs: list[float],
    rolling_probs: list[float],
    model_probs: list[float],
    model_type: str,
) -> dict[str, object]:
    actuals = [int(row["_actual"]) for row in test_rows]
    return {
        "target": target,
        "test_event_id": test_event_id,
        "test_event_name": test_event_name,
        "test_event_date": test_event_date,
        "train_rows": train_row_count,
        "test_rows": len(test_rows),
        "train_positive_rate": format_float(train_positive_rate),
        "actual_rate": format_float(sum(actuals) / len(actuals)),
        "avg_base_rate_prob": format_float(average(base_probs)),
        "avg_player_rolling_prob": format_float(average(rolling_probs)),
        "avg_model_prob": format_float(average(model_probs)),
        "base_rate_brier": format_float(brier_score(actuals, base_probs)),
        "player_rolling_brier": format_float(brier_score(actuals, rolling_probs)),
        "model_brier": format_float(brier_score(actuals, model_probs)),
        "base_rate_log_loss": format_float(log_loss(actuals, base_probs)),
        "player_rolling_log_loss": format_float(log_loss(actuals, rolling_probs)),
        "model_log_loss": format_float(log_loss(actuals, model_probs)),
        "model_type": model_type,
    }


def build_calibration_rows(predictions: list[dict[str, object]]) -> list[dict[str, object]]:
    buckets: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in predictions:
        probability = float(row["model_prob"])
        bucket_start = min(int(probability * 10) * 10, 90)
        bucket = f"{bucket_start:02d}-{bucket_start + 10:02d}"
        buckets[(str(row["target"]), str(row["model_type"]), bucket)].append(row)

    calibration_rows = []
    for (target, model_type, bucket), bucket_rows in sorted(buckets.items()):
        actuals = [int(row["actual"]) for row in bucket_rows]
        probs = [float(row["model_prob"]) for row in bucket_rows]
        calibration_rows.append(
            {
                "target": target,
                "model_type": model_type,
                "probability_bucket": bucket,
                "rows": len(bucket_rows),
                "avg_predicted": format_float(average(probs)),
                "actual_rate": format_float(sum(actuals) / len(actuals)),
            }
        )
    return calibration_rows


def build_report(metrics: list[dict[str, object]], predictions: list[dict[str, object]]) -> str:
    lines = ["Time-split baseline report", ""]
    lines.append(f"metrics_rows: {len(metrics)}")
    lines.append(f"prediction_rows: {len(predictions)}")
    lines.append("")
    for row in metrics:
        lines.append(
            "{target} {date}: train={train} test={test} model={model} "
            "brier={brier}".format(
                target=row["target"],
                date=row["test_event_date"],
                train=row["train_rows"],
                test=row["test_rows"],
                model=row["model_type"],
                brier=row["model_brier"],
            )
        )
    return "\n".join(lines) + "\n"


def run_time_split_baseline(
    features_path: Path,
    output_dir: Path,
    min_train_rows: int = 10,
    min_prior_starts: int = 3,
    model: str = "base_rate",
    enable_logistic: bool = False,
) -> dict[str, list[dict[str, object]]]:
    if model not in {"base_rate", "player_rolling", "logistic"}:
        raise BaselineError(f"unknown model: {model}")
    if enable_logistic:
        model = "logistic"

    rows = read_csv(features_path)
    predictions: list[dict[str, object]] = []
    metrics: list[dict[str, object]] = []

    for target in TARGET_COLUMNS:
        rows_for_target = eligible_rows(rows, target)
        rows_by_date: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in sorted(rows_for_target, key=lambda item: (str(item["event_date_start"]), str(item["event_id"]))):
            rows_by_date[str(row["event_date_start"])].append(row)

        train_rows: list[dict[str, object]] = []
        train_row_count = 0
        train_positive_count = 0
        for test_date in sorted(rows_by_date):
            test_rows = rows_by_date[test_date]
            if not train_rows or not test_rows:
                train_rows.extend(test_rows)
                train_row_count += len(test_rows)
                train_positive_count += sum(int(row["_actual"]) for row in test_rows)
                continue

            base_probability = train_positive_count / train_row_count
            base_probs = [base_probability] * len(test_rows)
            rolling_probs = player_rolling_probs(
                target,
                test_rows,
                base_probability,
                min_prior_starts,
            )
            if model == "player_rolling":
                model_type = "player_rolling"
                model_probs = rolling_probs
            elif model == "logistic":
                model_type, logistic_probs = fit_logistic_predict(
                    train_rows,
                    test_rows,
                    min_train_rows,
                    True,
                )
                model_probs = logistic_probs if logistic_probs is not None else base_probs
            else:
                model_type = "base_rate"
                model_probs = base_probs

            test_event_id = str(test_rows[0]["event_id"])
            test_event_name = str(test_rows[0].get("event_name", ""))
            metrics.append(
                build_metrics_row(
                    target,
                    test_event_id,
                    test_event_name,
                    test_date,
                    train_row_count,
                    base_probability,
                    test_rows,
                    base_probs,
                    rolling_probs,
                    model_probs,
                    model_type,
                )
            )

            for row, base_prob, rolling_prob, model_prob in zip(
                test_rows,
                base_probs,
                rolling_probs,
                model_probs,
            ):
                predictions.append(
                    {
                        "target": target,
                        "event_id": row["event_id"],
                        "event_name": row.get("event_name"),
                        "event_date_start": row["event_date_start"],
                        "season": row.get("season"),
                        "player_id": row["player_id"],
                        "player_name": row.get("player_name"),
                        "course_id": row.get("course_id"),
                        "course_name": row.get("course_name"),
                        "actual": row["_actual"],
                        "base_rate_prob": format_float(base_prob),
                        "player_rolling_prob": format_float(rolling_prob),
                        "model_prob": format_float(model_prob),
                        "model_type": model_type,
                    }
                )

            train_rows.extend(test_rows)
            train_row_count += len(test_rows)
            train_positive_count += sum(int(row["_actual"]) for row in test_rows)

    calibration = build_calibration_rows(predictions)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "metrics.csv", METRIC_COLUMNS, metrics)
    write_csv(output_dir / "predictions.csv", PREDICTION_COLUMNS, predictions)
    write_csv(output_dir / "calibration.csv", CALIBRATION_COLUMNS, calibration)
    (output_dir / "report.txt").write_text(build_report(metrics, predictions), encoding="utf-8")

    return {
        "metrics": metrics,
        "predictions": predictions,
        "calibration": calibration,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="time-split-baseline")
    parser.add_argument("--features", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--min-train-rows", type=int, default=10)
    parser.add_argument("--min-prior-starts", type=int, default=3)
    parser.add_argument(
        "--model",
        choices=["base_rate", "player_rolling", "logistic"],
        default="base_rate",
    )
    parser.add_argument("--enable-logistic", action="store_true")
    args = parser.parse_args(argv)

    run_time_split_baseline(
        args.features,
        args.output_dir,
        args.min_train_rows,
        args.min_prior_starts,
        args.model,
        args.enable_logistic,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
