"""Reviewed event registry: next-event scope and event-structure decisions."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from golf_props.config import PROJECT_ROOT
from golf_props.features.current_event import normalize_name
from golf_props.models.tournament_simulator import (
    CUT_RULE_NO_CUT,
    CUT_RULE_TOP_N_AND_TIES,
    SUPPORTED_CUT_RULES,
)

DEFAULT_REGISTRY_PATH = PROJECT_ROOT / "config" / "event_registry.csv"

REGISTRY_COLUMNS = [
    "season",
    "source_event_id",
    "event_name",
    "include",
    "format",
    "rounds",
    "cut_rule",
    "cut_size",
    "decision_status",
    "reviewed_at_utc",
    "notes",
]

DEFAULT_FORMAT = "72_hole_stroke_play"
DEFAULT_ROUNDS = 4
DEFAULT_CUT_SIZE = 65
STATUS_REVIEWED = "reviewed"
STATUS_DEFAULT = "default"


class EventRegistryError(ValueError):
    """Raised when the reviewed event registry is missing or malformed."""


def read_registry(path: Path = DEFAULT_REGISTRY_PATH) -> list[dict[str, str]]:
    if not path.exists():
        raise EventRegistryError(f"missing event registry: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _parse_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def registry_rows_for(
    rows: list[dict[str, str]],
    season: int,
    event_name: str,
    source_event_id: str = "",
) -> list[dict[str, str]]:
    name_key = normalize_name(event_name)
    matches = []
    for row in rows:
        try:
            row_season = int(str(row.get("season") or "").strip())
        except ValueError:
            continue
        if row_season != season:
            continue
        row_name = str(row.get("event_name") or "").strip()
        row_source_id = str(row.get("source_event_id") or "").strip()
        if not row_name:
            continue
        if source_event_id and row_source_id == source_event_id:
            matches.append(row)
            continue
        if normalize_name(row_name) == name_key:
            matches.append(row)
    return matches


def scope_status(
    rows: list[dict[str, str]],
    season: int,
    event_name: str,
    source_event_id: str = "",
) -> Optional[bool]:
    matches = registry_rows_for(rows, season, event_name, source_event_id)
    if not matches:
        return None
    return _parse_bool(matches[0].get("include"))


def resolve_structure(
    rows: list[dict[str, str]],
    season: int,
    event_name: str,
    source_event_id: str = "",
) -> Optional[dict[str, object]]:
    """Return a structure decision or None when the event is not usable."""
    matches = registry_rows_for(rows, season, event_name, source_event_id)
    if not matches:
        return None
    row = matches[0]
    include = _parse_bool(row.get("include"))
    if include is not True:
        return None
    status = str(row.get("decision_status") or "").strip()
    if status != STATUS_REVIEWED:
        return None
    format_name = str(row.get("format") or DEFAULT_FORMAT).strip()
    try:
        rounds = int(str(row.get("rounds") or DEFAULT_ROUNDS).strip())
    except ValueError as exc:
        raise EventRegistryError(
            f"invalid rounds for {event_name}: {row.get('rounds')}"
        ) from exc
    cut_rule = str(row.get("cut_rule") or CUT_RULE_TOP_N_AND_TIES).strip()
    if cut_rule not in SUPPORTED_CUT_RULES:
        raise EventRegistryError(f"unsupported cut_rule {cut_rule} for {event_name}")
    try:
        cut_size = int(str(row.get("cut_size") or DEFAULT_CUT_SIZE).strip())
    except ValueError as exc:
        raise EventRegistryError(
            f"invalid cut_size for {event_name}: {row.get('cut_size')}"
        ) from exc
    if cut_rule == CUT_RULE_NO_CUT:
        cut_size = 0
    if format_name != DEFAULT_FORMAT or rounds != DEFAULT_ROUNDS:
        raise EventRegistryError(
            f"unsupported event structure {format_name}/{rounds} for {event_name}"
        )
    return {
        "event_name": str(row.get("event_name") or event_name).strip(),
        "season": season,
        "source_event_id": str(row.get("source_event_id") or "").strip(),
        "format": format_name,
        "rounds": rounds,
        "cut_rule": cut_rule,
        "cut_size": cut_size,
        "decision_status": status,
        "reviewed_at_utc": str(row.get("reviewed_at_utc") or "").strip(),
        "notes": str(row.get("notes") or "").strip(),
    }
