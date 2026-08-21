"""Normalize the Kaggle/ESPN PGA results TSV into canonical tables."""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
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
    "season",
    "start",
    "end",
    "tournament",
    "location",
    "position",
    "name",
    "score",
    "round1",
    "round2",
    "round3",
    "round4",
    "total",
    "earnings",
    "fedex_points",
}

ROUND_COLUMNS = ["round1", "round2", "round3", "round4"]
NON_FINISH_STATUSES = {"CUT", "CUT", "WD", "DNS", "DQ", "MDF"}


class EspnResultsNormalizationError(ValueError):
    """Raised when ESPN/Kaggle rows cannot be normalized safely."""


def stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(part.strip().lower() for part in parts if part is not None)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def blank_to_none(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse_int(value: Optional[str]) -> Optional[int]:
    value = blank_to_none(value)
    if value is None:
        return None
    return int(value.replace(",", ""))


def parse_float(value: Optional[str]) -> Optional[float]:
    value = blank_to_none(value)
    if value is None:
        return None
    return float(value.replace(",", ""))


def parse_score_to_par(value: Optional[str]) -> Optional[int]:
    value = blank_to_none(value)
    if value is None:
        return None
    if value.upper() == "E":
        return 0
    if re.fullmatch(r"[+-]?\d+", value):
        return int(value)
    return None


def parse_finish_position(value: str) -> Optional[int]:
    value = value.strip()
    if re.fullmatch(r"T?\d+", value):
        return int(value.removeprefix("T"))
    return None


def made_cut_from_position(position: str) -> Optional[bool]:
    normalized = position.strip().upper()
    if re.fullmatch(r"T?\d+", normalized):
        return True
    if normalized == "MDF":
        return True
    if normalized == "CUT":
        return False
    if normalized in {"WD", "DNS", "DQ"}:
        return False
    return None


def is_withdrawn(position: str) -> bool:
    return position.strip().upper() in {"WD", "DNS"}


def is_disqualified(position: str) -> bool:
    return position.strip().upper() == "DQ"


def read_rows(input_path: Path) -> list[dict[str, str]]:
    with input_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fieldnames = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - fieldnames)
        if missing:
            raise EspnResultsNormalizationError(
                f"missing required columns: {', '.join(missing)}"
            )
        return list(reader)


def empty_row(columns: Iterable[str]) -> dict[str, object]:
    return {column: None for column in columns}


def course_name_from_location(location: Optional[str], tournament: str) -> str:
    location = blank_to_none(location)
    if location is None:
        return f"Unknown Course - {tournament}"
    return location


def normalize_rows(rows: list[dict[str, str]], source: str = "espn_kaggle") -> dict[str, list[dict[str, object]]]:
    events: OrderedDict[str, dict[str, object]] = OrderedDict()
    courses: OrderedDict[str, dict[str, object]] = OrderedDict()
    players: OrderedDict[str, dict[str, object]] = OrderedDict()
    event_courses: OrderedDict[str, dict[str, object]] = OrderedDict()
    results: list[dict[str, object]] = []
    round_scores: list[dict[str, object]] = []

    for index, row in enumerate(rows, start=1):
        season = required_value(row, "season", index)
        start = required_value(row, "start", index)
        end = required_value(row, "end", index)
        tournament = required_value(row, "tournament", index)
        player_name = required_value(row, "name", index)
        position = required_value(row, "position", index)
        source_event_id = f"{season}_{start}_{tournament}"
        course_name = course_name_from_location(row.get("location"), tournament)

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
                    "tour": "PGA",
                    "season": parse_int(season),
                    "event_name": tournament,
                    "date_start": start,
                    "date_end": end,
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

        result_id = stable_id("result", source_event_id, player_name)
        result = empty_row(PLAYER_EVENT_RESULTS_COLUMNS)
        result.update(
            {
                "result_id": result_id,
                "event_id": event_id,
                "player_id": player_id,
                "finish_position": parse_finish_position(position),
                "finish_text": position,
                "made_cut": made_cut_from_position(position),
                "withdrawn": is_withdrawn(position),
                "disqualified": is_disqualified(position),
                "total_score": parse_int(row.get("total")),
                "total_to_par": parse_score_to_par(row.get("score")),
                "rounds_played": count_rounds(row),
                "earnings": parse_float(row.get("earnings")),
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
                        "round", source_event_id, player_name, str(round_number)
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
        raise EspnResultsNormalizationError(f"row {row_number} missing required value: {column}")
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


def build_quality_report(
    tables: dict[str, list[dict[str, object]]],
    raw_rows: list[dict[str, str]],
) -> str:
    position_counts: dict[str, int] = {}
    blank_locations = 0
    for row in raw_rows:
        position = row["position"]
        if re.fullmatch(r"T?\d+", position):
            position = "finished"
        else:
            position = position.upper()
        position_counts[position] = position_counts.get(position, 0) + 1
        if not blank_to_none(row.get("location")):
            blank_locations += 1

    lines = ["ESPN/Kaggle PGA results normalization report", ""]
    for name in [
        "events",
        "courses",
        "players",
        "event_courses",
        "player_event_results",
        "round_scores",
    ]:
        lines.append(f"{name}: {len(tables[name])} rows")
    lines.extend(["", f"raw_rows: {len(raw_rows)}", f"blank_locations: {blank_locations}", ""])
    lines.append("position_counts:")
    for position, count in sorted(position_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"  {position}: {count}")
    return "\n".join(lines) + "\n"


def write_outputs(
    tables: dict[str, list[dict[str, object]]],
    output_dir: Path,
    raw_rows: list[dict[str, str]],
) -> None:
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
        build_quality_report(tables, raw_rows),
        encoding="utf-8",
    )


def normalize_file(input_path: Path, output_dir: Path) -> dict[str, list[dict[str, object]]]:
    raw_rows = read_rows(input_path)
    tables = normalize_rows(raw_rows)
    write_outputs(tables, output_dir, raw_rows)
    return tables


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="normalize-espn-results")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    normalize_file(args.input, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
