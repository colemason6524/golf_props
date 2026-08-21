"""Build leakage-safe player-event features from canonical PGA tables."""

from __future__ import annotations

import argparse
import csv
import hashlib
from collections import defaultdict, OrderedDict
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Iterable, Optional

from golf_props.schemas import FEATURES_PLAYER_EVENT_COLUMNS


class FeatureBuildError(ValueError):
    """Raised when canonical inputs cannot produce player-event features."""


def stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(part.strip().lower() for part in parts if part is not None)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FeatureBuildError(f"missing input table: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_date(value: str) -> date:
    if not value:
        raise FeatureBuildError("event row missing date_start")
    return date.fromisoformat(value)


def parse_bool(value: str) -> Optional[bool]:
    if value == "":
        return None
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    raise FeatureBuildError(f"invalid bool value: {value}")


def parse_int(value: str) -> Optional[int]:
    if value == "":
        return None
    return int(value)


def parse_float(value: str) -> Optional[float]:
    if value == "":
        return None
    return float(value)


def safe_mean(values: Iterable[Optional[float]]) -> Optional[float]:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return round(mean(clean), 6)


def safe_rate(values: Iterable[Optional[bool]]) -> Optional[float]:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return round(sum(1 for value in clean if value) / len(clean), 6)


def recent_weight(index: int) -> int:
    if index <= 5:
        return 3
    if index <= 10:
        return 2
    return 1


def weighted_recent_values(rows: list[dict[str, object]], key: str) -> list[tuple[object, int]]:
    ordered = sorted(rows, key=lambda row: row["event_date"], reverse=True)
    return [(row.get(key), recent_weight(index)) for index, row in enumerate(ordered, start=1)]


def safe_weighted_mean(weighted_values: Iterable[tuple[Optional[float], int]]) -> Optional[float]:
    clean = [(value, weight) for value, weight in weighted_values if value is not None]
    if not clean:
        return None
    total_weight = sum(weight for _, weight in clean)
    return round(sum(float(value) * weight for value, weight in clean) / total_weight, 6)


def safe_weighted_rate(weighted_values: Iterable[tuple[Optional[bool], int]]) -> Optional[float]:
    clean = [(value, weight) for value, weight in weighted_values if value is not None]
    if not clean:
        return None
    total_weight = sum(weight for _, weight in clean)
    return round(sum((1 if value else 0) * weight for value, weight in clean) / total_weight, 6)


def target_at_or_better(
    finish_position: Optional[int],
    threshold: int,
    made_cut: Optional[bool],
    withdrawn: bool,
    disqualified: bool,
) -> Optional[bool]:
    if finish_position is None:
        if made_cut is False and not withdrawn and not disqualified:
            return False
        return None
    return finish_position <= threshold


def normalize_event_name(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def is_open_championship(event_name: str) -> bool:
    normalized = normalize_event_name(event_name)
    return "the open championship" in normalized or normalized == "open championship"


def is_major(event_name: str) -> bool:
    normalized = normalize_event_name(event_name)
    return any(
        marker in normalized
        for marker in [
            "masters tournament",
            "pga championship",
            "u.s. open",
            "us open",
            "the open championship",
        ]
    )


def primary_course_by_event(event_courses: list[dict[str, str]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in event_courses:
        event_id = row["event_id"]
        if event_id not in mapping or row.get("is_primary_course") == "True":
            mapping[event_id] = row["course_id"]
    return mapping


def build_features(input_dir: Path, output_path: Path) -> list[dict[str, object]]:
    events = read_csv(input_dir / "events.csv")
    event_courses = read_csv(input_dir / "event_courses.csv")
    courses = read_csv(input_dir / "courses.csv")
    players = read_csv(input_dir / "players.csv")
    results = read_csv(input_dir / "player_event_results.csv")

    event_by_id = {row["event_id"]: row for row in events}
    course_by_id = {row["course_id"]: row for row in courses}
    player_by_id = {row["player_id"]: row for row in players}
    course_by_event = primary_course_by_event(event_courses)
    field_size_by_event = defaultdict(int)
    for result in results:
        field_size_by_event[result["event_id"]] += 1

    enriched_results = []
    for result in results:
        event = event_by_id.get(result["event_id"])
        if event is None:
            raise FeatureBuildError(f"result references unknown event: {result['event_id']}")
        course_id = course_by_event.get(result["event_id"])
        if course_id is None:
            raise FeatureBuildError(f"event missing course mapping: {result['event_id']}")
        course = course_by_id.get(course_id)
        if course is None:
            raise FeatureBuildError(f"event references unknown course: {course_id}")
        player = player_by_id.get(result["player_id"])
        if player is None:
            raise FeatureBuildError(f"result references unknown player: {result['player_id']}")
        finish_position = parse_int(result.get("finish_position", ""))
        made_cut = parse_bool(result.get("made_cut", ""))
        withdrawn = parse_bool(result.get("withdrawn", "")) or False
        disqualified = parse_bool(result.get("disqualified", "")) or False
        enriched_results.append(
            {
                **result,
                "event_date": parse_date(event["date_start"]),
                "event_name": event["event_name"],
                "is_major_event": is_major(event["event_name"]),
                "is_open_event": is_open_championship(event["event_name"]),
                "season": event["season"],
                "course_id": course_id,
                "course_name": course["course_name"],
                "player_name": player["player_name"],
                "finish_position_int": finish_position,
                "made_cut_bool": made_cut,
                "total_to_par_float": parse_float(result.get("total_to_par", "")),
                "target_top20_bool": target_at_or_better(
                    finish_position, 20, made_cut, withdrawn, disqualified
                ),
                "target_top10_bool": target_at_or_better(
                    finish_position, 10, made_cut, withdrawn, disqualified
                ),
                "target_top5_bool": target_at_or_better(
                    finish_position, 5, made_cut, withdrawn, disqualified
                ),
                "target_win_bool": target_at_or_better(
                    finish_position, 1, made_cut, withdrawn, disqualified
                ),
            }
        )

    feature_rows: list[dict[str, object]] = []
    history_by_player: dict[str, list[dict[str, object]]] = defaultdict(list)
    events_in_order: OrderedDict[tuple[date, str], list[dict[str, object]]] = OrderedDict()
    for row in sorted(
        enriched_results,
        key=lambda item: (item["event_date"], item["event_id"], item["player_id"]),
    ):
        events_in_order.setdefault((row["event_date"], row["event_id"]), []).append(row)

    for _, event_rows in events_in_order.items():
        for current in event_rows:
            prior = history_by_player[current["player_id"]]
            prior_at_course = [row for row in prior if row["course_id"] == current["course_id"]]
            prior_majors = [row for row in prior if row["is_major_event"]]
            prior_opens = [row for row in prior if row["is_open_event"]]

            prior_dates = sorted(row["event_date"] for row in prior)
            days_since_last_start = None
            if prior_dates:
                days_since_last_start = (current["event_date"] - prior_dates[-1]).days

            feature_row = {
                "feature_row_id": stable_id("feature", current["event_id"], current["player_id"]),
                "event_id": current["event_id"],
                "event_name": current["event_name"],
                "player_id": current["player_id"],
                "player_name": current["player_name"],
                "course_id": current["course_id"],
                "course_name": current["course_name"],
                "season": current["season"],
                "feature_timestamp_utc": f"{current['event_date'].isoformat()}T00:00:00Z",
                "event_date_start": current["event_date"].isoformat(),
                "field_size": field_size_by_event[current["event_id"]],
                "prior_starts": len(prior),
                "days_since_last_start": days_since_last_start,
                "recent_made_cut_rate": safe_rate(row["made_cut_bool"] for row in prior),
                "recent_top20_rate": safe_rate(row["target_top20_bool"] for row in prior),
                "recent_top10_rate": safe_rate(row["target_top10_bool"] for row in prior),
                "recent_top5_rate": safe_rate(row["target_top5_bool"] for row in prior),
                "recent_win_rate": safe_rate(row["target_win_bool"] for row in prior),
                "weighted_recent_made_cut_rate": safe_weighted_rate(
                    weighted_recent_values(prior, "made_cut_bool")
                ),
                "weighted_recent_top20_rate": safe_weighted_rate(
                    weighted_recent_values(prior, "target_top20_bool")
                ),
                "weighted_recent_top10_rate": safe_weighted_rate(
                    weighted_recent_values(prior, "target_top10_bool")
                ),
                "weighted_recent_top5_rate": safe_weighted_rate(
                    weighted_recent_values(prior, "target_top5_bool")
                ),
                "weighted_recent_win_rate": safe_weighted_rate(
                    weighted_recent_values(prior, "target_win_bool")
                ),
                "weighted_recent_avg_finish": safe_weighted_mean(
                    weighted_recent_values(prior, "finish_position_int")
                ),
                "weighted_recent_avg_score_to_par": safe_weighted_mean(
                    weighted_recent_values(prior, "total_to_par_float")
                ),
                "recent_avg_finish": safe_mean(row["finish_position_int"] for row in prior),
                "recent_avg_score_to_par": safe_mean(row["total_to_par_float"] for row in prior),
                "course_starts": len(prior_at_course),
                "course_made_cut_rate": safe_rate(row["made_cut_bool"] for row in prior_at_course),
                "course_top20_rate": safe_rate(row["target_top20_bool"] for row in prior_at_course),
                "course_win_rate": safe_rate(row["target_win_bool"] for row in prior_at_course),
                "course_avg_finish": safe_mean(row["finish_position_int"] for row in prior_at_course),
                "major_starts": len(prior_majors),
                "major_made_cut_rate": safe_rate(row["made_cut_bool"] for row in prior_majors),
                "major_top20_rate": safe_rate(row["target_top20_bool"] for row in prior_majors),
                "major_top10_rate": safe_rate(row["target_top10_bool"] for row in prior_majors),
                "major_top5_rate": safe_rate(row["target_top5_bool"] for row in prior_majors),
                "major_win_rate": safe_rate(row["target_win_bool"] for row in prior_majors),
                "major_avg_finish": safe_mean(row["finish_position_int"] for row in prior_majors),
                "open_starts": len(prior_opens),
                "open_made_cut_rate": safe_rate(row["made_cut_bool"] for row in prior_opens),
                "open_top20_rate": safe_rate(row["target_top20_bool"] for row in prior_opens),
                "open_top10_rate": safe_rate(row["target_top10_bool"] for row in prior_opens),
                "open_top5_rate": safe_rate(row["target_top5_bool"] for row in prior_opens),
                "open_win_rate": safe_rate(row["target_win_bool"] for row in prior_opens),
                "open_avg_finish": safe_mean(row["finish_position_int"] for row in prior_opens),
                "target_make_cut": current["made_cut_bool"],
                "target_top20": current["target_top20_bool"],
                "target_top10": current["target_top10_bool"],
                "target_top5": current["target_top5_bool"],
                "target_win": current["target_win_bool"],
            }
            feature_rows.append(feature_row)

        for current in event_rows:
            history_by_player[current["player_id"]].append(current)

    write_csv(output_path, FEATURES_PLAYER_EVENT_COLUMNS, feature_rows)
    return feature_rows


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="build-player-event-features")
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    build_features(args.input_dir, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
