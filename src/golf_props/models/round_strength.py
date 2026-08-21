"""Estimate point-in-time player strength from relative round performance."""

from __future__ import annotations

import argparse
import csv
import json
import math
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Optional

from golf_props.features.current_event import normalize_name, validate_field_columns
from golf_props.features.player_event import stable_id

ROUND_STRENGTH_COLUMNS = [
    "player_id",
    "player_name",
    "entry_status",
    "player_match_status",
    "as_of_date",
    "rounds_used",
    "effective_rounds",
    "history_start_date",
    "history_end_date",
    "long_term_mean_relative",
    "recent_90_mean_relative",
    "recent_365_mean_relative",
    "weighted_mean_relative",
    "shrunk_mean_relative",
    "weighted_std_relative",
    "shrunk_std_relative",
]


class RoundStrengthError(ValueError):
    """Raised when a point-in-time strength snapshot cannot be estimated."""


@dataclass(frozen=True)
class PreparedRoundHistory:
    """Parsed and date-indexed round history reusable across as-of snapshots."""

    rows_by_player: dict[str, list[dict[str, object]]]
    dates_by_player: dict[str, list[date]]
    name_by_id: dict[str, str]
    ids_by_name: dict[str, list[str]]
    global_dates: list[date]
    global_value_prefix: list[float]
    global_square_prefix: list[float]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise RoundStrengthError(f"missing input file: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=ROUND_STRENGTH_COLUMNS,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def weighted_mean(values: list[float], weights: list[float]) -> float:
    total_weight = sum(weights)
    if total_weight <= 0:
        return 0.0
    return sum(value * weight for value, weight in zip(values, weights)) / total_weight


def weighted_variance(
    values: list[float],
    weights: list[float],
    center: float,
) -> float:
    total_weight = sum(weights)
    if total_weight <= 0:
        return 0.0
    return (
        sum(weight * (value - center) ** 2 for value, weight in zip(values, weights))
        / total_weight
    )


def mean_in_window(
    rows: list[dict[str, object]],
    as_of_date: date,
    days: int,
) -> Optional[float]:
    values = [
        float(row["relative_to_field"])
        for row in rows
        if 0 <= (as_of_date - row["event_end"]).days <= days
    ]
    return round(mean(values), 6) if values else None


def eligible_round_rows(
    round_rows: list[dict[str, str]],
    as_of_date: date,
) -> list[dict[str, object]]:
    eligible = []
    for row in round_rows:
        completion = date.fromisoformat(
            row.get("event_date_end") or row["event_date_start"]
        )
        if completion >= as_of_date:
            continue
        eligible.append(
            {
                **row,
                "event_end": completion,
                "relative_to_field": float(row["relative_to_field"]),
            }
        )
    return eligible


def player_maps(
    round_rows: list[dict[str, str]],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    name_by_id: dict[str, str] = {}
    ids_by_name: dict[str, list[str]] = defaultdict(list)
    for row in round_rows:
        player_id = row["player_id"]
        player_name = row.get("player_name", "")
        name_by_id[player_id] = player_name
        key = normalize_name(player_name)
        if key and player_id not in ids_by_name[key]:
            ids_by_name[key].append(player_id)
    return name_by_id, ids_by_name


def prepare_round_history(
    round_rows: list[dict[str, str]],
) -> PreparedRoundHistory:
    """Parse and sort history once for repeated point-in-time estimates."""
    rows_by_player: dict[str, list[dict[str, object]]] = defaultdict(list)
    name_by_id, ids_by_name = player_maps(round_rows)
    global_rows: list[tuple[date, float]] = []
    for row in round_rows:
        completion = date.fromisoformat(
            row.get("event_date_end") or row["event_date_start"]
        )
        value = float(row["relative_to_field"])
        parsed = {
            **row,
            "event_end": completion,
            "relative_to_field": value,
        }
        rows_by_player[row["player_id"]].append(parsed)
        global_rows.append((completion, value))

    dates_by_player: dict[str, list[date]] = {}
    for player_id, rows in rows_by_player.items():
        rows.sort(key=lambda row: (row["event_end"], str(row.get("event_id", ""))))
        dates_by_player[player_id] = [row["event_end"] for row in rows]

    global_rows.sort(key=lambda item: item[0])
    global_dates = [item[0] for item in global_rows]
    value_prefix = [0.0]
    square_prefix = [0.0]
    for _, value in global_rows:
        value_prefix.append(value_prefix[-1] + value)
        square_prefix.append(square_prefix[-1] + value * value)
    return PreparedRoundHistory(
        rows_by_player=dict(rows_by_player),
        dates_by_player=dates_by_player,
        name_by_id=name_by_id,
        ids_by_name=ids_by_name,
        global_dates=global_dates,
        global_value_prefix=value_prefix,
        global_square_prefix=square_prefix,
    )


def match_player(
    field_row: dict[str, str],
    name_by_id: dict[str, str],
    ids_by_name: dict[str, list[str]],
) -> tuple[str, str]:
    supplied_id = str(field_row.get("player_id") or "").strip()
    if supplied_id:
        if supplied_id in name_by_id:
            return supplied_id, "matched_player_id"
        return supplied_id, "unknown_player_id"
    candidates = ids_by_name.get(normalize_name(field_row.get("player_name")), [])
    if len(candidates) == 1:
        return candidates[0], "matched_player_name"
    if len(candidates) > 1:
        return stable_id("player_current", field_row["player_name"]), "ambiguous_player_name"
    return stable_id("player_current", field_row["player_name"]), "unmatched_player_name"


def estimate_strength_rows(
    round_rows: list[dict[str, str]],
    field_rows: list[dict[str, str]],
    as_of_date: str,
    half_life_days: float = 180.0,
    prior_rounds: float = 20.0,
    variance_prior_rounds: float = 20.0,
    prepared_history: Optional[PreparedRoundHistory] = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    if half_life_days <= 0:
        raise RoundStrengthError("half_life_days must be positive")
    if prior_rounds < 0 or variance_prior_rounds < 0:
        raise RoundStrengthError("prior round counts cannot be negative")
    cutoff = date.fromisoformat(as_of_date)
    prepared = prepared_history or prepare_round_history(round_rows)
    eligible_count = bisect_left(prepared.global_dates, cutoff)
    if eligible_count:
        global_sum = prepared.global_value_prefix[eligible_count]
        global_square_sum = prepared.global_square_prefix[eligible_count]
        global_mean = global_sum / eligible_count
        global_variance = max(
            global_square_sum / eligible_count - global_mean * global_mean,
            0.0,
        )
    else:
        global_mean = 0.0
        global_variance = 9.0
    global_std = math.sqrt(max(global_variance, 1e-9))

    output = []
    status_counts: dict[str, int] = defaultdict(int)
    for field_row in field_rows:
        player_id, match_status = match_player(
            field_row,
            prepared.name_by_id,
            prepared.ids_by_name,
        )
        player_dates = prepared.dates_by_player.get(player_id, [])
        history_end = bisect_left(player_dates, cutoff)
        history = prepared.rows_by_player.get(player_id, [])[:history_end]
        values = [float(row["relative_to_field"]) for row in history]
        weights = [
            math.exp(
                -math.log(2)
                * max((cutoff - row["event_end"]).days, 0)
                / half_life_days
            )
            for row in history
        ]
        weighted_player_mean = (
            weighted_mean(values, weights) if values else global_mean
        )
        weighted_player_variance = (
            weighted_variance(values, weights, weighted_player_mean)
            if values
            else global_variance
        )
        # The sum of decay weights is the number of current-equivalent rounds.
        # Unlike a scale-invariant statistical ESS, it lets entirely stale
        # histories lose reliability and shrink back toward the tour mean.
        effective_rounds = sum(weights)
        mean_reliability = (
            effective_rounds / (effective_rounds + prior_rounds)
            if effective_rounds + prior_rounds > 0
            else 0.0
        )
        shrunk_mean = (
            mean_reliability * weighted_player_mean
            + (1 - mean_reliability) * global_mean
        )
        shrunk_variance = (
            effective_rounds * weighted_player_variance
            + variance_prior_rounds * global_variance
        ) / max(effective_rounds + variance_prior_rounds, 1e-9)
        if not history and match_status.startswith("matched_"):
            match_status = "matched_no_prior_rounds"
        status_counts[match_status] += 1
        output.append(
            {
                "player_id": player_id,
                "player_name": str(field_row["player_name"]).strip(),
                "entry_status": str(field_row.get("entry_status") or "").strip(),
                "player_match_status": match_status,
                "as_of_date": as_of_date,
                "rounds_used": len(history),
                "effective_rounds": round(effective_rounds, 6),
                "history_start_date": (
                    min(row["event_end"] for row in history).isoformat()
                    if history
                    else ""
                ),
                "history_end_date": (
                    max(row["event_end"] for row in history).isoformat()
                    if history
                    else ""
                ),
                "long_term_mean_relative": (
                    round(mean(values), 6) if values else round(global_mean, 6)
                ),
                "recent_90_mean_relative": mean_in_window(history, cutoff, 90),
                "recent_365_mean_relative": mean_in_window(history, cutoff, 365),
                "weighted_mean_relative": round(weighted_player_mean, 6),
                "shrunk_mean_relative": round(shrunk_mean, 6),
                "weighted_std_relative": round(
                    math.sqrt(max(weighted_player_variance, 0.0)),
                    6,
                ),
                "shrunk_std_relative": round(
                    math.sqrt(max(shrunk_variance, 1e-9)),
                    6,
                ),
            }
        )

    summary = {
        "as_of_date": as_of_date,
        "field_rows": len(field_rows),
        "eligible_historical_rounds": eligible_count,
        "global_mean_relative": round(global_mean, 6),
        "global_std_relative": round(global_std, 6),
        "half_life_days": half_life_days,
        "prior_rounds": prior_rounds,
        "variance_prior_rounds": variance_prior_rounds,
        "match_status_counts": dict(sorted(status_counts.items())),
    }
    return output, summary


def render_report(summary: dict[str, object]) -> str:
    lines = [
        "# Round Strength Snapshot",
        "",
        "Strength is positive when a player is expected to score better than the",
        "event-round field average.",
        "",
    ]
    for key, value in summary.items():
        if key == "match_status_counts":
            continue
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Match Status", "", "| Status | Rows |", "|---|---:|"])
    counts = summary["match_status_counts"]
    assert isinstance(counts, dict)
    for status, count in counts.items():
        lines.append(f"| {status} | {count} |")
    return "\n".join(lines).rstrip() + "\n"


def build_round_strength_snapshot(
    round_performance_path: Path,
    field_path: Path,
    output_path: Path,
    as_of_date: str,
    report_path: Optional[Path] = None,
    half_life_days: float = 180.0,
    prior_rounds: float = 20.0,
    variance_prior_rounds: float = 20.0,
) -> dict[str, object]:
    field_rows = read_csv(field_path)
    validate_field_columns(field_path, field_rows)
    rows, summary = estimate_strength_rows(
        read_csv(round_performance_path),
        field_rows,
        as_of_date,
        half_life_days=half_life_days,
        prior_rounds=prior_rounds,
        variance_prior_rounds=variance_prior_rounds,
    )
    write_csv(output_path, rows)
    report_path = report_path or output_path.with_suffix(".report.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(summary), encoding="utf-8")
    report_path.with_suffix(".json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "rows": rows,
        "summary": summary,
        "output_path": output_path,
        "report_path": report_path,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="build-round-strength")
    parser.add_argument("--round-performance", required=True, type=Path)
    parser.add_argument("--field", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report-output", type=Path)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--half-life-days", type=float, default=180.0)
    parser.add_argument("--prior-rounds", type=float, default=20.0)
    parser.add_argument("--variance-prior-rounds", type=float, default=20.0)
    args = parser.parse_args(argv)

    result = build_round_strength_snapshot(
        args.round_performance,
        args.field,
        args.output,
        args.as_of_date,
        report_path=args.report_output,
        half_life_days=args.half_life_days,
        prior_rounds=args.prior_rounds,
        variance_prior_rounds=args.variance_prior_rounds,
    )
    print(f"round_strength_output={result['output_path']}")
    print(f"round_strength_rows={len(result['rows'])}")
    print(f"round_strength_report={result['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
