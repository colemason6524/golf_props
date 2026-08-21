"""Normalize manually entered sportsbook odds snapshots."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
from typing import Iterable, Optional

from golf_props.schemas import ODDS_SNAPSHOTS_COLUMNS

REQUIRED_COLUMNS = {
    "captured_at_utc",
    "sportsbook",
    "event_name",
    "season",
    "market_type",
    "player_name",
    "price_american",
}

SUPPORTED_MARKETS = {"winner", "make_cut", "top20", "top10", "top5"}


class ManualOddsError(ValueError):
    """Raised when manual odds rows cannot be normalized."""


def stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(str(part).strip().lower() for part in parts if part is not None)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def blank_to_none(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse_american_odds(value: Optional[str]) -> int:
    value = blank_to_none(value)
    if value is None:
        raise ManualOddsError("price_american is required")
    cleaned = value.replace("+", "")
    return int(cleaned)


def american_to_decimal(price: int) -> float:
    if price > 0:
        return round(1 + price / 100, 6)
    if price < 0:
        return round(1 + 100 / abs(price), 6)
    raise ManualOddsError("American odds cannot be zero")


def american_to_implied_probability(price: int) -> float:
    if price > 0:
        return round(100 / (price + 100), 6)
    if price < 0:
        return round(abs(price) / (abs(price) + 100), 6)
    raise ManualOddsError("American odds cannot be zero")


def read_rows(input_path: Path) -> list[dict[str, str]]:
    with input_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - fieldnames)
        if missing:
            raise ManualOddsError(f"missing required columns: {', '.join(missing)}")
        return list(reader)


def empty_row(columns: Iterable[str]) -> dict[str, object]:
    return {column: None for column in columns}


def normalize_rows(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    normalized_rows = []
    for index, row in enumerate(rows, start=1):
        market_type = required_value(row, "market_type", index).lower()
        if market_type not in SUPPORTED_MARKETS:
            raise ManualOddsError(f"row {index} unsupported market_type: {market_type}")
        sportsbook = required_value(row, "sportsbook", index)
        event_name = required_value(row, "event_name", index)
        season = required_value(row, "season", index)
        player_name = required_value(row, "player_name", index)
        captured_at_utc = required_value(row, "captured_at_utc", index)
        price_american = parse_american_odds(row.get("price_american"))

        odds_id = stable_id(
            "odds",
            captured_at_utc,
            sportsbook,
            event_name,
            season,
            market_type,
            player_name,
            row.get("line"),
            price_american,
        )

        odds_row = empty_row(ODDS_SNAPSHOTS_COLUMNS)
        odds_row.update(
            {
                "odds_id": odds_id,
                "event_id": blank_to_none(row.get("event_id")),
                "event_name": event_name,
                "season": season,
                "player_id": blank_to_none(row.get("player_id")),
                "player_name": player_name,
                "sportsbook": sportsbook,
                "market_type": market_type,
                "market_name": blank_to_none(row.get("market_name")) or market_type,
                "selection_name": blank_to_none(row.get("selection_name")) or player_name,
                "line": blank_to_none(row.get("line")),
                "price_american": price_american,
                "price_decimal": american_to_decimal(price_american),
                "implied_probability": american_to_implied_probability(price_american),
                "captured_at_utc": captured_at_utc,
                "source_url": blank_to_none(row.get("source_url")),
                "market_status": blank_to_none(row.get("market_status")) or "open",
                "is_closing_candidate": parse_bool(row.get("is_closing_candidate")) or False,
            }
        )
        normalized_rows.append(odds_row)
    return normalized_rows


def required_value(row: dict[str, str], column: str, row_number: int) -> str:
    value = blank_to_none(row.get(column))
    if value is None:
        raise ManualOddsError(f"row {row_number} missing required value: {column}")
    return value


def parse_bool(value: Optional[str]) -> Optional[bool]:
    value = blank_to_none(value)
    if value is None:
        return None
    normalized = value.lower()
    if normalized in {"true", "t", "yes", "y", "1"}:
        return True
    if normalized in {"false", "f", "no", "n", "0"}:
        return False
    raise ManualOddsError(f"invalid boolean value: {value}")


def write_output(rows: list[dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ODDS_SNAPSHOTS_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def normalize_file(input_path: Path, output_path: Path) -> list[dict[str, object]]:
    rows = normalize_rows(read_rows(input_path))
    write_output(rows, output_path)
    return rows


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="normalize-manual-odds")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    normalize_file(args.input, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
