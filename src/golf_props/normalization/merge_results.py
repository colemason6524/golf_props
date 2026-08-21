"""Merge canonical PGA result directories while preserving historical player IDs."""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from pathlib import Path
from typing import Iterable, Optional

from golf_props.schemas import (
    COURSE_ALIASES_COLUMNS,
    COURSES_COLUMNS,
    EVENT_COURSES_COLUMNS,
    EVENTS_COLUMNS,
    PLAYER_EVENT_RESULTS_COLUMNS,
    PLAYERS_COLUMNS,
    ROUND_SCORES_COLUMNS,
)
from golf_props.normalization.course_identity import load_accepted_course_aliases

TABLE_COLUMNS = {
    "events": EVENTS_COLUMNS,
    "courses": COURSES_COLUMNS,
    "players": PLAYERS_COLUMNS,
    "event_courses": EVENT_COURSES_COLUMNS,
    "player_event_results": PLAYER_EVENT_RESULTS_COLUMNS,
    "round_scores": ROUND_SCORES_COLUMNS,
}


class MergeResultsError(ValueError):
    """Raised when canonical result directories cannot be merged."""


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise MergeResultsError(f"missing table: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, columns: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def normalize_name(value: object) -> str:
    text = str(value or "").strip().casefold()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def remap_player_ids(base_players: list[dict[str, str]], add_players: list[dict[str, str]]) -> dict[str, str]:
    base_by_name = {normalize_name(row["player_name"]): row["player_id"] for row in base_players}
    mapping = {}
    for row in add_players:
        normalized = normalize_name(row["player_name"])
        mapping[row["player_id"]] = base_by_name.get(normalized, row["player_id"])
    return mapping


def merge_by_id(
    base_rows: list[dict[str, str]],
    add_rows: list[dict[str, str]],
    id_column: str,
) -> list[dict[str, str]]:
    merged = {row[id_column]: row for row in base_rows}
    for row in add_rows:
        merged.setdefault(row[id_column], row)
    return list(merged.values())


def apply_player_mapping(rows: list[dict[str, str]], mapping: dict[str, str]) -> list[dict[str, str]]:
    mapped = []
    for row in rows:
        new_row = dict(row)
        player_id = new_row.get("player_id")
        if player_id in mapping:
            new_row["player_id"] = mapping[player_id]
        mapped.append(new_row)
    return mapped


def apply_course_mapping(
    rows: list[dict[str, str]],
    mapping: dict[str, str],
) -> list[dict[str, str]]:
    mapped = []
    for row in rows:
        new_row = dict(row)
        course_id = new_row.get("course_id")
        if course_id in mapping:
            new_row["course_id"] = mapping[course_id]
        mapped.append(new_row)
    return mapped


def merge_directories(
    base_dir: Path,
    add_dir: Path,
    output_dir: Path,
    course_aliases_path: Optional[Path] = None,
) -> dict[str, list[dict[str, str]]]:
    base = {table: read_csv(base_dir / f"{table}.csv") for table in TABLE_COLUMNS}
    add = {table: read_csv(add_dir / f"{table}.csv") for table in TABLE_COLUMNS}
    player_mapping = remap_player_ids(base["players"], add["players"])
    all_courses = base["courses"] + add["courses"]
    course_mapping: dict[str, str] = {}
    course_aliases: list[dict[str, str]] = []
    if course_aliases_path is not None:
        course_mapping, course_aliases = load_accepted_course_aliases(
            course_aliases_path,
            all_courses,
        )

    mapped_add_players = [
        row for row in add["players"] if player_mapping.get(row["player_id"], row["player_id"]) == row["player_id"]
    ]
    mapped_add_results = apply_player_mapping(add["player_event_results"], player_mapping)
    mapped_base_rounds = apply_course_mapping(base["round_scores"], course_mapping)
    mapped_add_rounds = apply_course_mapping(
        apply_player_mapping(add["round_scores"], player_mapping),
        course_mapping,
    )
    mapped_base_event_courses = apply_course_mapping(base["event_courses"], course_mapping)
    mapped_add_event_courses = apply_course_mapping(add["event_courses"], course_mapping)
    canonical_courses = [
        row for row in all_courses if course_mapping.get(row["course_id"], row["course_id"]) == row["course_id"]
    ]

    tables = {
        "events": merge_by_id(base["events"], add["events"], "event_id"),
        "courses": merge_by_id([], canonical_courses, "course_id"),
        "players": merge_by_id(base["players"], mapped_add_players, "player_id"),
        "event_courses": mapped_base_event_courses + mapped_add_event_courses,
        "player_event_results": base["player_event_results"] + mapped_add_results,
        "round_scores": mapped_base_rounds + mapped_add_rounds,
    }
    for table, rows in tables.items():
        write_csv(output_dir / f"{table}.csv", TABLE_COLUMNS[table], rows)
    if course_aliases_path is not None:
        write_csv(
            output_dir / "course_aliases.csv",
            COURSE_ALIASES_COLUMNS,
            course_aliases,
        )
        tables["course_aliases"] = course_aliases
    return tables


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="merge-results")
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--add", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--course-aliases", type=Path)
    args = parser.parse_args(argv)

    merge_directories(
        args.base,
        args.add,
        args.output_dir,
        course_aliases_path=args.course_aliases,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
