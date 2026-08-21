"""Leakage-safe same-course residual adjustments for round strength."""

from __future__ import annotations

import math
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PreparedCourseHistory:
    rows_by_player_course: dict[tuple[str, str], list[dict[str, object]]]
    dates_by_player_course: dict[tuple[str, str], list[date]]


class CourseAdjustmentError(ValueError):
    """Raised when a course adjustment cannot be estimated."""


def prepare_course_history(
    round_rows: list[dict[str, str]],
) -> PreparedCourseHistory:
    rows_by_key: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in round_rows:
        course_id = str(row.get("course_id") or "").strip()
        player_id = str(row.get("player_id") or "").strip()
        if not course_id or not player_id:
            continue
        completion = date.fromisoformat(
            row.get("event_date_end") or row["event_date_start"]
        )
        rows_by_key[(player_id, course_id)].append(
            {
                **row,
                "event_end": completion,
                "relative_to_field": float(row["relative_to_field"]),
            }
        )
    dates_by_key = {}
    for key, rows in rows_by_key.items():
        rows.sort(
            key=lambda row: (
                row["event_end"],
                str(row.get("event_id", "")),
                int(row.get("round_number") or 0),
            )
        )
        dates_by_key[key] = [row["event_end"] for row in rows]
    return PreparedCourseHistory(dict(rows_by_key), dates_by_key)


def apply_course_adjustment(
    strength_rows: list[dict[str, object]],
    course_id: str,
    as_of_date: str,
    history: PreparedCourseHistory,
    half_life_days: float,
    course_prior_rounds: float,
    adjustment_weight: float,
    max_absolute_adjustment: float = 2.0,
) -> list[dict[str, object]]:
    """Adjust expected relative performance using prior same-course residuals."""
    if half_life_days <= 0:
        raise CourseAdjustmentError("half_life_days must be positive")
    if course_prior_rounds < 0:
        raise CourseAdjustmentError("course_prior_rounds cannot be negative")
    if adjustment_weight < 0:
        raise CourseAdjustmentError("adjustment_weight cannot be negative")
    if max_absolute_adjustment < 0:
        raise CourseAdjustmentError("max_absolute_adjustment cannot be negative")

    cutoff = date.fromisoformat(as_of_date)
    output = []
    for source in strength_rows:
        player_id = str(source.get("player_id") or "")
        key = (player_id, course_id)
        dates = history.dates_by_player_course.get(key, [])
        history_end = bisect_left(dates, cutoff)
        prior_rows = history.rows_by_player_course.get(key, [])[:history_end]
        weights = [
            math.exp(
                -math.log(2)
                * max((cutoff - row["event_end"]).days, 0)
                / half_life_days
            )
            for row in prior_rows
        ]
        effective_rounds = sum(weights)
        if effective_rounds > 0:
            course_mean = sum(
                float(row["relative_to_field"]) * weight
                for row, weight in zip(prior_rows, weights)
            ) / effective_rounds
            player_mean = float(source["weighted_mean_relative"])
            residual = course_mean - player_mean
            reliability = effective_rounds / (
                effective_rounds + course_prior_rounds
            )
            shrunk_residual = reliability * residual
            unbounded_adjustment = adjustment_weight * shrunk_residual
            adjustment = max(
                min(unbounded_adjustment, max_absolute_adjustment),
                -max_absolute_adjustment,
            )
        else:
            course_mean = None
            residual = None
            shrunk_residual = 0.0
            adjustment = 0.0
        output.append(
            {
                **source,
                "course_id": course_id,
                "course_rounds_used": len(prior_rows),
                "course_effective_rounds": round(effective_rounds, 6),
                "course_mean_relative": (
                    "" if course_mean is None else round(course_mean, 6)
                ),
                "course_residual_relative": (
                    "" if residual is None else round(residual, 6)
                ),
                "course_shrunk_residual": round(shrunk_residual, 6),
                "course_adjustment": round(adjustment, 6),
                "shrunk_mean_relative": round(
                    float(source["shrunk_mean_relative"]) + adjustment,
                    6,
                ),
            }
        )
    return output
