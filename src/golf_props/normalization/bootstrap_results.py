"""Normalize a simple PGA historical-results CSV into canonical tables."""

from __future__ import annotations

import argparse
import csv
import hashlib
from collections import OrderedDict
from pathlib import Path
from typing import Iterable, Optional

from golf_props.schemas import (
    COURSES_COLUMNS,
    EVENT_COURSES_COLUMNS,
    EVENTS_COLUMNS,
    PLAYER_EVENT_RESULTS_COLUMNS,
    PLAYERS_COLUMNS,
    ROUND_SCORES_COLUMNS,
)

REQUIRED_COLUMNS = {
    "source",
    "source_event_id",
    "event_name",
    "date_start",
    "date_end",
    "course_name",
    "tour",
    "season",
    "player_name",
    "finish_text",
    "made_cut",
}

ROUND_COLUMNS = ["r1", "r2", "r3", "r4"]


class NormalizationError(ValueError):
    """Raised when bootstrap results cannot be normalized safely."""


def stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(part.strip().lower() for part in parts if part is not None)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def blank_to_none(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse_bool(value: Optional[str]) -> Optional[bool]:
    value = blank_to_none(value)
    if value is None:
        return None
    normalized = value.lower()
    if normalized in {"true", "t", "yes", "y", "1"}:
        return True
    if normalized in {"false", "f", "no", "n", "0"}:
        return False
    raise NormalizationError(f"invalid boolean value: {value}")


def parse_int(value: Optional[str]) -> Optional[int]:
    value = blank_to_none(value)
    if value is None:
        return None
    return int(value.replace(",", ""))


def read_rows(input_path: Path) -> list[dict[str, str]]:
    with input_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - fieldnames)
        if missing:
            raise NormalizationError(f"missing required columns: {', '.join(missing)}")
        return list(reader)


def empty_row(columns: Iterable[str]) -> dict[str, object]:
    return {column: None for column in columns}


def normalize_rows(rows: list[dict[str, str]]) -> dict[str, list[dict[str, object]]]:
    events: OrderedDict[str, dict[str, object]] = OrderedDict()
    courses: OrderedDict[str, dict[str, object]] = OrderedDict()
    players: OrderedDict[str, dict[str, object]] = OrderedDict()
    event_courses: OrderedDict[str, dict[str, object]] = OrderedDict()
    results: list[dict[str, object]] = []
    round_scores: list[dict[str, object]] = []

    for index, row in enumerate(rows, start=1):
        source = required_value(row, "source", index)
        source_event_id = required_value(row, "source_event_id", index)
        event_name = required_value(row, "event_name", index)
        course_name = required_value(row, "course_name", index)
        player_name = required_value(row, "player_name", index)

        event_id = stable_id("event", source, source_event_id)
        course_id = stable_id("course", source, course_name)
        player_id = stable_id("player", source, player_name)

        if event_id not in events:
            event = empty_row(EVENTS_COLUMNS)
            event.update(
                {
                    "event_id": event_id,
                    "source": source,
                    "source_event_id": source_event_id,
                    "tour": blank_to_none(row.get("tour")),
                    "season": parse_int(row.get("season")),
                    "event_name": event_name,
                    "date_start": blank_to_none(row.get("date_start")),
                    "date_end": blank_to_none(row.get("date_end")),
                    "format": "stroke_play",
                    "created_at_utc": None,
                }
            )
            events[event_id] = event

        if course_id not in courses:
            course = empty_row(COURSES_COLUMNS)
            course.update(
                {
                    "course_id": course_id,
                    "source": source,
                    "source_course_id": course_name,
                    "course_name": course_name,
                    "created_at_utc": None,
                }
            )
            courses[course_id] = course

        if player_id not in players:
            player = empty_row(PLAYERS_COLUMNS)
            player.update(
                {
                    "player_id": player_id,
                    "source": source,
                    "source_player_id": player_name,
                    "player_name": player_name,
                    "created_at_utc": None,
                }
            )
            players[player_id] = player

        event_course_key = f"{event_id}|{course_id}|"
        if event_course_key not in event_courses:
            event_course = empty_row(EVENT_COURSES_COLUMNS)
            event_course.update(
                {
                    "event_id": event_id,
                    "course_id": course_id,
                    "round_number": None,
                    "is_primary_course": True,
                    "notes": None,
                }
            )
            event_courses[event_course_key] = event_course

        result_id = stable_id("result", source, source_event_id, player_name)
        result = empty_row(PLAYER_EVENT_RESULTS_COLUMNS)
        result.update(
            {
                "result_id": result_id,
                "event_id": event_id,
                "player_id": player_id,
                "finish_position": parse_int(row.get("finish_position")),
                "finish_text": blank_to_none(row.get("finish_text")),
                "made_cut": parse_bool(row.get("made_cut")),
                "withdrawn": parse_bool(row.get("withdrawn")) or False,
                "disqualified": parse_bool(row.get("disqualified")) or False,
                "total_score": parse_int(row.get("total_score")),
                "total_to_par": parse_int(row.get("total_to_par")),
                "rounds_played": count_rounds(row),
                "earnings": parse_int(row.get("earnings")),
                "recorded_at_utc": None,
            }
        )
        results.append(result)

        for round_number, column in enumerate(ROUND_COLUMNS, start=1):
            score = parse_int(row.get(column))
            if score is None:
                continue
            round_score = empty_row(ROUND_SCORES_COLUMNS)
            round_score.update(
                {
                    "round_score_id": stable_id(
                        "round", source, source_event_id, player_name, str(round_number)
                    ),
                    "event_id": event_id,
                    "course_id": course_id,
                    "player_id": player_id,
                    "round_number": round_number,
                    "score": score,
                    "recorded_at_utc": None,
                }
            )
            round_scores.append(round_score)

    return {
        "events": list(events.values()),
        "courses": list(courses.values()),
        "players": list(players.values()),
        "event_courses": list(event_courses.values()),
        "player_event_results": results,
        "round_scores": round_scores,
    }


def required_value(row: dict[str, str], column: str, row_number: int) -> str:
    value = blank_to_none(row.get(column))
    if value is None:
        raise NormalizationError(f"row {row_number} missing required value: {column}")
    return value


def count_rounds(row: dict[str, str]) -> int:
    return sum(1 for column in ROUND_COLUMNS if blank_to_none(row.get(column)) is not None)


def write_table(output_dir: Path, name: str, columns: list[str], rows: list[dict[str, object]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_quality_report(tables: dict[str, list[dict[str, object]]]) -> str:
    lines = ["Bootstrap PGA results normalization report", ""]
    for name in [
        "events",
        "courses",
        "players",
        "event_courses",
        "player_event_results",
        "round_scores",
    ]:
        lines.append(f"{name}: {len(tables[name])} rows")

    missing_finish = sum(
        1
        for row in tables["player_event_results"]
        if row.get("finish_position") is None and not row.get("withdrawn")
    )
    withdrawn = sum(1 for row in tables["player_event_results"] if row.get("withdrawn"))
    lines.extend(
        [
            "",
            f"missing_finish_position_non_withdrawn: {missing_finish}",
            f"withdrawn_results: {withdrawn}",
        ]
    )
    return "\n".join(lines) + "\n"


def write_outputs(tables: dict[str, list[dict[str, object]]], output_dir: Path) -> None:
    write_table(output_dir, "events", EVENTS_COLUMNS, tables["events"])
    write_table(output_dir, "courses", COURSES_COLUMNS, tables["courses"])
    write_table(output_dir, "players", PLAYERS_COLUMNS, tables["players"])
    write_table(output_dir, "event_courses", EVENT_COURSES_COLUMNS, tables["event_courses"])
    write_table(
        output_dir,
        "player_event_results",
        PLAYER_EVENT_RESULTS_COLUMNS,
        tables["player_event_results"],
    )
    write_table(output_dir, "round_scores", ROUND_SCORES_COLUMNS, tables["round_scores"])
    (output_dir / "data_quality_report.txt").write_text(
        build_quality_report(tables),
        encoding="utf-8",
    )


def normalize_file(input_path: Path, output_dir: Path) -> dict[str, list[dict[str, object]]]:
    rows = read_rows(input_path)
    tables = normalize_rows(rows)
    write_outputs(tables, output_dir)
    return tables


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="bootstrap-results")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    normalize_file(args.input, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
