"""Normalize CBS Sports PGA leaderboard pages into canonical result tables."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
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

ROUND_COUNT = 4


class CbsNormalizationError(ValueError):
    """Raised when CBS result pages cannot be normalized."""


def stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(str(part).strip().casefold() for part in parts if part is not None)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def empty_row(columns: Iterable[str]) -> dict[str, object]:
    return {column: None for column in columns}


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def strip_tags(value: str) -> str:
    return clean_text(re.sub(r"<.*?>", "", value))


def parse_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    value = re.sub(r"[^0-9-]", "", value)
    if not value or value == "-":
        return None
    return int(value)


def parse_money(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    value = value.strip()
    if value in {"", "-"}:
        return None
    return float(value.replace("$", "").replace(",", ""))


def parse_score_to_par(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    value = value.strip()
    if value == "E":
        return 0
    if re.fullmatch(r"[+-]?\d+", value):
        return int(value)
    return None


def parse_finish_position(value: str) -> Optional[int]:
    if re.fullmatch(r"T?\d+", value.strip()):
        return int(value.strip().removeprefix("T"))
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


def parse_leaderboard_rows(page_html: str) -> list[dict[str, object]]:
    rows = []
    table_rows = re.findall(
        r'<tr class="TableBase-bodyTr GolfLeaderboard-bodyTr.*?</tr>',
        page_html,
        flags=re.S,
    )
    for row_html in table_rows:
        long_name_match = re.search(r'CellPlayerName--long.*?<a[^>]*>(.*?)</a>', row_html, flags=re.S)
        if not long_name_match:
            continue
        player_name = strip_tags(long_name_match.group(1))
        cells = [strip_tags(cell) for cell in re.findall(r"<td\b[^>]*>(.*?)</td>", row_html, flags=re.S)]
        if len(cells) < 11:
            continue
        position = cells[1]
        round_values = [parse_int(value) for value in cells[6:10]]
        rows.append(
            {
                "position": position,
                "player_name": player_name,
                "total_to_par": parse_score_to_par(cells[4]),
                "earnings": parse_money(cells[5]),
                "round_scores": round_values,
                "total_score": parse_int(cells[10]),
                "rounds_played": sum(1 for score in round_values if score is not None),
            }
        )
    return rows


def normalize_collected(input_dir: Path, source: str = "cbs_sports") -> dict[str, list[dict[str, object]]]:
    metadata_path = input_dir / "metadata.json"
    if not metadata_path.exists():
        raise CbsNormalizationError(f"missing metadata file: {metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    events: OrderedDict[str, dict[str, object]] = OrderedDict()
    courses: OrderedDict[str, dict[str, object]] = OrderedDict()
    players: OrderedDict[str, dict[str, object]] = OrderedDict()
    event_courses: OrderedDict[str, dict[str, object]] = OrderedDict()
    results: list[dict[str, object]] = []
    round_scores: list[dict[str, object]] = []

    for event_meta in metadata.get("events", []):
        raw_path = Path(str(event_meta["raw_path"]))
        page_html = raw_path.read_text(encoding="utf-8")
        event_name = str(event_meta["event_name"])
        source_event_id = re.sub(r"^.*?/(\d+)/.*$", r"\1", str(event_meta["url"]))
        event_id = stable_id("event", source, source_event_id)
        course_name = str(event_meta.get("course_name") or f"Unknown Course - {event_name}").strip()
        course_id = stable_id("course", source, course_name)

        event = empty_row(EVENTS_COLUMNS)
        event.update(
            {
                "event_id": event_id,
                "source": source,
                "source_event_id": source_event_id,
                "tour": "PGA",
                "season": int(str(event_meta["date_start"])[:4]),
                "event_name": event_name,
                "date_start": event_meta["date_start"],
                "date_end": event_meta["date_end"],
                "format": "stroke_play",
                "created_at_utc": metadata.get("captured_at_utc"),
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
                    "location": event_meta.get("location"),
                    "created_at_utc": metadata.get("captured_at_utc"),
                }
            )
            courses[course_id] = course

        event_course_key = f"{event_id}|{course_id}|"
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

        for leaderboard_row in parse_leaderboard_rows(page_html):
            player_name = str(leaderboard_row["player_name"])
            player_id = stable_id("player", source, player_name)
            if player_id not in players:
                player = empty_row(PLAYERS_COLUMNS)
                player.update(
                    {
                        "player_id": player_id,
                        "source": source,
                        "source_player_id": player_name,
                        "player_name": player_name,
                        "created_at_utc": metadata.get("captured_at_utc"),
                    }
                )
                players[player_id] = player

            position = str(leaderboard_row["position"])
            result = empty_row(PLAYER_EVENT_RESULTS_COLUMNS)
            result.update(
                {
                    "result_id": stable_id("result", source_event_id, player_name),
                    "event_id": event_id,
                    "player_id": player_id,
                    "finish_position": parse_finish_position(position),
                    "finish_text": position,
                    "made_cut": made_cut_from_position(position),
                    "withdrawn": is_withdrawn(position),
                    "disqualified": is_disqualified(position),
                    "total_score": leaderboard_row["total_score"],
                    "total_to_par": leaderboard_row["total_to_par"],
                    "rounds_played": leaderboard_row["rounds_played"],
                    "earnings": leaderboard_row["earnings"],
                    "recorded_at_utc": metadata.get("captured_at_utc"),
                }
            )
            results.append(result)

            for index, score in enumerate(leaderboard_row["round_scores"], start=1):
                if score is None:
                    continue
                round_score = empty_row(ROUND_SCORES_COLUMNS)
                round_score.update(
                    {
                        "round_score_id": stable_id("round", source_event_id, player_name, str(index)),
                        "event_id": event_id,
                        "course_id": course_id,
                        "player_id": player_id,
                        "round_number": index,
                        "score": score,
                        "recorded_at_utc": metadata.get("captured_at_utc"),
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


def write_table(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def normalize_directory(input_dir: Path, output_dir: Path) -> dict[str, list[dict[str, object]]]:
    tables = normalize_collected(input_dir)
    write_table(output_dir / "events.csv", EVENTS_COLUMNS, tables["events"])
    write_table(output_dir / "courses.csv", COURSES_COLUMNS, tables["courses"])
    write_table(output_dir / "players.csv", PLAYERS_COLUMNS, tables["players"])
    write_table(output_dir / "event_courses.csv", EVENT_COURSES_COLUMNS, tables["event_courses"])
    write_table(output_dir / "player_event_results.csv", PLAYER_EVENT_RESULTS_COLUMNS, tables["player_event_results"])
    write_table(output_dir / "round_scores.csv", ROUND_SCORES_COLUMNS, tables["round_scores"])
    return tables


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="normalize-cbs-results")
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    normalize_directory(args.input_dir, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
