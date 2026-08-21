"""Build point-in-time current-event features from canonical PGA results."""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

from golf_props.features.player_event import (
    FeatureBuildError,
    is_major,
    is_open_championship,
    parse_bool,
    parse_date,
    parse_float,
    parse_int,
    primary_course_by_event,
    recent_weight,
    safe_mean,
    safe_rate,
    safe_weighted_mean,
    safe_weighted_rate,
    stable_id,
    target_at_or_better,
)
from golf_props.schemas import CURRENT_EVENT_FEATURES_COLUMNS

FIELD_REQUIRED_COLUMNS = {"player_name"}
TARGET_COLUMNS = {
    "target_make_cut",
    "target_top20",
    "target_top10",
    "target_top5",
    "target_win",
}


class CurrentEventFeatureError(FeatureBuildError):
    """Raised when a current-event feature snapshot cannot be built."""


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise CurrentEventFeatureError(f"missing input file: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=CURRENT_EVENT_FEATURES_COLUMNS,
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def normalize_name(value: object) -> str:
    text = str(value or "").strip().casefold()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def validate_field_columns(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise CurrentEventFeatureError(f"current field is empty: {path}")
    missing = FIELD_REQUIRED_COLUMNS - set(rows[0])
    if missing:
        raise CurrentEventFeatureError(
            f"current field missing required columns: {', '.join(sorted(missing))}"
        )
    seen: set[str] = set()
    for index, row in enumerate(rows, start=2):
        player_name = str(row.get("player_name") or "").strip()
        if not player_name:
            raise CurrentEventFeatureError(
                f"current field row {index} missing player_name"
            )
        key = normalize_name(player_name)
        if key in seen:
            raise CurrentEventFeatureError(
                f"current field has duplicate player_name: {player_name}"
            )
        seen.add(key)


def weighted_values(
    rows: list[dict[str, object]],
    key: str,
) -> list[tuple[object, int]]:
    ordered = sorted(rows, key=lambda row: row["event_date"], reverse=True)
    return [
        (row.get(key), recent_weight(index))
        for index, row in enumerate(ordered, start=1)
    ]


def completed_before(event: dict[str, str], as_of_date: date) -> bool:
    completion_value = event.get("date_end") or event.get("date_start")
    if not completion_value:
        raise CurrentEventFeatureError(
            f"historical event missing date_start/date_end: {event.get('event_id', '')}"
        )
    return parse_date(completion_value) < as_of_date


def enrich_history(
    input_dir: Path,
    as_of_date: date,
) -> tuple[
    list[dict[str, object]],
    dict[str, dict[str, str]],
    dict[str, list[str]],
]:
    events = read_csv(input_dir / "events.csv")
    event_courses = read_csv(input_dir / "event_courses.csv")
    courses = read_csv(input_dir / "courses.csv")
    players = read_csv(input_dir / "players.csv")
    results = read_csv(input_dir / "player_event_results.csv")

    eligible_events = {
        row["event_id"]: row for row in events if completed_before(row, as_of_date)
    }
    course_by_id = {row["course_id"]: row for row in courses}
    course_by_event = primary_course_by_event(event_courses)
    player_by_id = {row["player_id"]: row for row in players}
    player_ids_by_name: dict[str, list[str]] = defaultdict(list)
    for player in players:
        key = normalize_name(player.get("player_name"))
        if key:
            player_ids_by_name[key].append(player["player_id"])

    history: list[dict[str, object]] = []
    for result in results:
        event = eligible_events.get(result["event_id"])
        if event is None:
            continue
        player = player_by_id.get(result["player_id"])
        if player is None:
            raise CurrentEventFeatureError(
                f"result references unknown player: {result['player_id']}"
            )
        course_id = course_by_event.get(result["event_id"], "")
        course = course_by_id.get(course_id, {})
        finish_position = parse_int(result.get("finish_position", ""))
        made_cut = parse_bool(result.get("made_cut", ""))
        withdrawn = parse_bool(result.get("withdrawn", "")) or False
        disqualified = parse_bool(result.get("disqualified", "")) or False
        event_start = parse_date(event["date_start"])
        event_end = parse_date(event.get("date_end") or event["date_start"])
        history.append(
            {
                **result,
                "event_date": event_start,
                "event_end": event_end,
                "event_name": event["event_name"],
                "course_id": course_id,
                "course_name": course.get("course_name", ""),
                "course_name_normalized": normalize_name(course.get("course_name", "")),
                "player_name": player["player_name"],
                "finish_position_int": finish_position,
                "made_cut_bool": made_cut,
                "total_to_par_float": parse_float(result.get("total_to_par", "")),
                "is_major_event": is_major(event["event_name"]),
                "is_open_event": is_open_championship(event["event_name"]),
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
    return history, player_by_id, player_ids_by_name


def match_field_player(
    field_row: dict[str, str],
    player_by_id: dict[str, dict[str, str]],
    player_ids_by_name: dict[str, list[str]],
) -> tuple[str, str]:
    supplied_player_id = str(field_row.get("player_id") or "").strip()
    if supplied_player_id:
        if supplied_player_id in player_by_id:
            return supplied_player_id, "matched_player_id"
        return supplied_player_id, "unknown_player_id"

    candidates = player_ids_by_name.get(normalize_name(field_row.get("player_name")), [])
    if len(candidates) == 1:
        return candidates[0], "matched_player_name"
    if len(candidates) > 1:
        return stable_id("player_current", field_row["player_name"]), "ambiguous_player_name"
    return stable_id("player_current", field_row["player_name"]), "unmatched_player_name"


def current_course_id(
    course_name: str,
    historical_rows: list[dict[str, object]],
) -> str:
    normalized = normalize_name(course_name)
    matches = sorted(
        {
            str(row.get("course_id") or "")
            for row in historical_rows
            if normalized
            and row.get("course_id")
            and row.get("course_name_normalized") == normalized
        }
    )
    if matches:
        return matches[0]
    return stable_id("course_current", course_name) if course_name else ""


def build_player_feature_row(
    field_row: dict[str, str],
    player_id: str,
    match_status: str,
    prior: list[dict[str, object]],
    event_id: str,
    event_name: str,
    event_date: date,
    season: int,
    course_id: str,
    course_name: str,
    field_size: int,
) -> dict[str, object]:
    prior = sorted(prior, key=lambda row: (row["event_date"], str(row["event_id"])))
    normalized_course = normalize_name(course_name)
    prior_at_course = [
        row
        for row in prior
        if normalized_course and row.get("course_name_normalized") == normalized_course
    ]
    prior_majors = [row for row in prior if row["is_major_event"]]
    prior_opens = [row for row in prior if row["is_open_event"]]
    days_since_last_start = (
        (event_date - prior[-1]["event_date"]).days if prior else None
    )

    row: dict[str, object] = {
        column: "" for column in CURRENT_EVENT_FEATURES_COLUMNS
    }
    row.update(
        {
            "feature_row_id": stable_id("feature_current", event_id, player_id),
            "event_id": event_id,
            "event_name": event_name,
            "player_id": player_id,
            "player_name": field_row["player_name"].strip(),
            "course_id": course_id,
            "course_name": course_name,
            "season": season,
            "feature_timestamp_utc": f"{event_date.isoformat()}T00:00:00Z",
            "event_date_start": event_date.isoformat(),
            "field_size": field_size,
            "prior_starts": len(prior),
            "days_since_last_start": days_since_last_start,
            "recent_made_cut_rate": safe_rate(r["made_cut_bool"] for r in prior),
            "recent_top20_rate": safe_rate(r["target_top20_bool"] for r in prior),
            "recent_top10_rate": safe_rate(r["target_top10_bool"] for r in prior),
            "recent_top5_rate": safe_rate(r["target_top5_bool"] for r in prior),
            "recent_win_rate": safe_rate(r["target_win_bool"] for r in prior),
            "weighted_recent_made_cut_rate": safe_weighted_rate(
                weighted_values(prior, "made_cut_bool")
            ),
            "weighted_recent_top20_rate": safe_weighted_rate(
                weighted_values(prior, "target_top20_bool")
            ),
            "weighted_recent_top10_rate": safe_weighted_rate(
                weighted_values(prior, "target_top10_bool")
            ),
            "weighted_recent_top5_rate": safe_weighted_rate(
                weighted_values(prior, "target_top5_bool")
            ),
            "weighted_recent_win_rate": safe_weighted_rate(
                weighted_values(prior, "target_win_bool")
            ),
            "weighted_recent_avg_finish": safe_weighted_mean(
                weighted_values(prior, "finish_position_int")
            ),
            "weighted_recent_avg_score_to_par": safe_weighted_mean(
                weighted_values(prior, "total_to_par_float")
            ),
            "recent_avg_finish": safe_mean(r["finish_position_int"] for r in prior),
            "recent_avg_score_to_par": safe_mean(
                r["total_to_par_float"] for r in prior
            ),
            "course_starts": len(prior_at_course),
            "course_made_cut_rate": safe_rate(
                r["made_cut_bool"] for r in prior_at_course
            ),
            "course_top20_rate": safe_rate(
                r["target_top20_bool"] for r in prior_at_course
            ),
            "course_win_rate": safe_rate(
                r["target_win_bool"] for r in prior_at_course
            ),
            "course_avg_finish": safe_mean(
                r["finish_position_int"] for r in prior_at_course
            ),
            "major_starts": len(prior_majors),
            "major_made_cut_rate": safe_rate(
                r["made_cut_bool"] for r in prior_majors
            ),
            "major_top20_rate": safe_rate(
                r["target_top20_bool"] for r in prior_majors
            ),
            "major_top10_rate": safe_rate(
                r["target_top10_bool"] for r in prior_majors
            ),
            "major_top5_rate": safe_rate(
                r["target_top5_bool"] for r in prior_majors
            ),
            "major_win_rate": safe_rate(
                r["target_win_bool"] for r in prior_majors
            ),
            "major_avg_finish": safe_mean(
                r["finish_position_int"] for r in prior_majors
            ),
            "open_starts": len(prior_opens),
            "open_made_cut_rate": safe_rate(r["made_cut_bool"] for r in prior_opens),
            "open_top20_rate": safe_rate(
                r["target_top20_bool"] for r in prior_opens
            ),
            "open_top10_rate": safe_rate(
                r["target_top10_bool"] for r in prior_opens
            ),
            "open_top5_rate": safe_rate(
                r["target_top5_bool"] for r in prior_opens
            ),
            "open_win_rate": safe_rate(r["target_win_bool"] for r in prior_opens),
            "open_avg_finish": safe_mean(
                r["finish_position_int"] for r in prior_opens
            ),
            "player_match_status": match_status,
            "history_through_date": (
                max(r["event_end"] for r in prior).isoformat() if prior else ""
            ),
        }
    )
    for target in TARGET_COLUMNS:
        row[target] = ""
    return row


def render_report(
    rows: list[dict[str, object]],
    input_dir: Path,
    field_path: Path,
    event_date: date,
) -> str:
    status_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        status_counts[str(row["player_match_status"])] += 1
    unmatched = [
        row
        for row in rows
        if not str(row["player_match_status"]).startswith("matched_")
    ]
    lines = [
        "# Current Event Feature Report",
        "",
        f"canonical_input: {input_dir}",
        f"field_input: {field_path}",
        f"event_date: {event_date.isoformat()}",
        f"field_rows: {len(rows)}",
        f"matched_rows: {len(rows) - len(unmatched)}",
        f"warning_rows: {len(unmatched)}",
        "",
        "## Match Status",
        "",
        "| Status | Rows |",
        "|---|---:|",
    ]
    for status, count in sorted(status_counts.items()):
        lines.append(f"| {status} | {count} |")
    if unmatched:
        lines.extend(["", "## Warnings", ""])
        for row in unmatched:
            lines.append(f"- {row['player_name']}: {row['player_match_status']}")
    return "\n".join(lines).rstrip() + "\n"


def build_current_event_features(
    input_dir: Path,
    field_path: Path,
    output_path: Path,
    event_name: str,
    event_date: str,
    course_name: str = "",
    season: Optional[int] = None,
    report_path: Optional[Path] = None,
) -> dict[str, object]:
    as_of_date = date.fromisoformat(event_date)
    season = season or as_of_date.year
    field_rows = read_csv(field_path)
    validate_field_columns(field_path, field_rows)
    historical_rows, player_by_id, player_ids_by_name = enrich_history(
        input_dir,
        as_of_date,
    )
    history_by_player: dict[str, list[dict[str, object]]] = defaultdict(list)
    for historical_row in historical_rows:
        history_by_player[str(historical_row["player_id"])].append(historical_row)

    event_id = stable_id("event_current", str(season), event_name, event_date)
    course_id = current_course_id(course_name, historical_rows)
    rows = []
    for field_row in field_rows:
        player_id, match_status = match_field_player(
            field_row,
            player_by_id,
            player_ids_by_name,
        )
        rows.append(
            build_player_feature_row(
                field_row,
                player_id,
                match_status,
                history_by_player.get(player_id, []),
                event_id,
                event_name,
                as_of_date,
                season,
                course_id,
                course_name,
                len(field_rows),
            )
        )

    write_csv(output_path, rows)
    report_path = report_path or output_path.with_suffix(".report.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(rows, input_dir, field_path, as_of_date),
        encoding="utf-8",
    )
    return {
        "rows": rows,
        "output_path": output_path,
        "report_path": report_path,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="build-current-event-features")
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--field", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report-output", type=Path)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--event-date", required=True)
    parser.add_argument("--course-name", default="")
    parser.add_argument("--season", type=int)
    args = parser.parse_args(argv)

    result = build_current_event_features(
        args.input_dir,
        args.field,
        args.output,
        event_name=args.event_name,
        event_date=args.event_date,
        course_name=args.course_name,
        season=args.season,
        report_path=args.report_output,
    )
    print(f"current_event_features={result['output_path']}")
    print(f"current_event_feature_report={result['report_path']}")
    print(f"current_event_feature_rows={len(result['rows'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
