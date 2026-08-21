"""Compare sportsbook odds snapshots and report price movement."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Optional

MOVEMENT_COLUMNS = [
    "sportsbook",
    "event_id",
    "event_name",
    "season",
    "player_id",
    "player_name",
    "market_type",
    "line",
    "previous_captured_at_utc",
    "current_captured_at_utc",
    "previous_price_american",
    "current_price_american",
    "previous_price_decimal",
    "current_price_decimal",
    "previous_implied_probability",
    "current_implied_probability",
    "implied_probability_change",
    "decimal_price_change",
    "direction",
    "movement_strength",
    "previous_source_url",
    "current_source_url",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_float(value: object) -> Optional[float]:
    if value in {None, ""}:
        return None
    return float(value)


def normalize_text(value: object) -> str:
    return str(value or "").strip().casefold()


def movement_key(row: dict[str, str]) -> tuple[str, str, str, str, str, str, str]:
    return (
        normalize_text(row.get("sportsbook")),
        normalize_text(row.get("event_name")),
        normalize_text(row.get("season")),
        normalize_text(row.get("player_name")),
        normalize_text(row.get("market_type")),
        normalize_text(row.get("line")),
        normalize_text(row.get("selection_name")),
    )


def snapshot_timestamp(path: Path) -> str:
    rows = read_csv(path)
    timestamps = sorted(
        row.get("captured_at_utc", "").strip()
        for row in rows
        if row.get("captured_at_utc", "").strip()
    )
    return timestamps[-1] if timestamps else path.stem


def history_snapshots(history_dir: Path) -> list[Path]:
    if not history_dir.exists():
        return []
    return sorted(
        [path for path in history_dir.glob("*.csv") if path.is_file()],
        key=lambda path: (snapshot_timestamp(path), path.name),
    )


def select_snapshot_pair(
    history_dir: Path,
    current_snapshot_path: Optional[Path] = None,
) -> tuple[Optional[Path], Optional[Path]]:
    snapshots = history_snapshots(history_dir)
    if not snapshots:
        return None, None
    current = current_snapshot_path if current_snapshot_path and current_snapshot_path.exists() else snapshots[-1]
    previous_candidates = [path for path in snapshots if path != current]
    if not previous_candidates:
        return None, current
    previous = previous_candidates[-1]
    return previous, current


def classify_direction(prob_change: float) -> str:
    if abs(prob_change) < 0.0005:
        return "unchanged"
    if prob_change > 0:
        return "steamed"
    return "drifted"


def classify_strength(prob_change: float) -> str:
    magnitude = abs(prob_change)
    if magnitude < 0.0005:
        return "none"
    if magnitude >= 0.05:
        return "large"
    if magnitude >= 0.02:
        return "medium"
    return "small"


def build_movement_rows(
    previous_rows: list[dict[str, str]],
    current_rows: list[dict[str, str]],
) -> list[dict[str, object]]:
    previous_by_key = {movement_key(row): row for row in previous_rows}
    movement_rows: list[dict[str, object]] = []

    for current in current_rows:
        previous = previous_by_key.get(movement_key(current))
        if previous is None:
            continue
        previous_prob = parse_float(previous.get("implied_probability"))
        current_prob = parse_float(current.get("implied_probability"))
        previous_decimal = parse_float(previous.get("price_decimal"))
        current_decimal = parse_float(current.get("price_decimal"))
        if previous_prob is None or current_prob is None:
            continue
        prob_change = current_prob - previous_prob
        decimal_change = (
            current_decimal - previous_decimal
            if previous_decimal is not None and current_decimal is not None
            else None
        )
        movement_rows.append(
            {
                "sportsbook": current.get("sportsbook"),
                "event_id": current.get("event_id"),
                "event_name": current.get("event_name"),
                "season": current.get("season"),
                "player_id": current.get("player_id"),
                "player_name": current.get("player_name"),
                "market_type": current.get("market_type"),
                "line": current.get("line"),
                "previous_captured_at_utc": previous.get("captured_at_utc"),
                "current_captured_at_utc": current.get("captured_at_utc"),
                "previous_price_american": previous.get("price_american"),
                "current_price_american": current.get("price_american"),
                "previous_price_decimal": previous.get("price_decimal"),
                "current_price_decimal": current.get("price_decimal"),
                "previous_implied_probability": previous.get("implied_probability"),
                "current_implied_probability": current.get("implied_probability"),
                "implied_probability_change": round(prob_change, 6),
                "decimal_price_change": round(decimal_change, 6) if decimal_change is not None else "",
                "direction": classify_direction(prob_change),
                "movement_strength": classify_strength(prob_change),
                "previous_source_url": previous.get("source_url"),
                "current_source_url": current.get("source_url"),
            }
        )

    return sorted(
        movement_rows,
        key=lambda row: (
            -abs(float(row["implied_probability_change"])),
            str(row["market_type"]),
            str(row["player_name"]),
        ),
    )


def render_markdown(
    movement_rows: list[dict[str, object]],
    previous_snapshot: Optional[Path],
    current_snapshot: Optional[Path],
    top_n: int,
) -> str:
    lines = ["# Odds Movement Report", ""]
    lines.append(f"previous_snapshot: {previous_snapshot or ''}")
    lines.append(f"current_snapshot: {current_snapshot or ''}")
    lines.append("")
    if previous_snapshot is None or current_snapshot is None:
        lines.append("Not enough snapshot history to compare yet.")
        return "\n".join(lines) + "\n"
    if not movement_rows:
        lines.append("No matched odds movement rows.")
        return "\n".join(lines) + "\n"

    sections = [
        ("Steam", "steamed"),
        ("Drift", "drifted"),
        ("Unchanged", "unchanged"),
    ]
    for title, direction in sections:
        rows = [row for row in movement_rows if row.get("direction") == direction]
        if top_n > 0:
            rows = rows[:top_n]
        lines.extend([f"## {title}", ""])
        if not rows:
            lines.extend(["No rows.", ""])
            continue
        lines.extend(table_lines(rows))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def table_lines(rows: list[dict[str, object]]) -> list[str]:
    lines = [
        "| Move | Player | Market | Prev | Curr | Prev Prob | Curr Prob | Strength |",
        "|---:|---|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            "| {move:+.3f} | {player} | {market} | {prev} | {curr} | {prev_prob:.3f} | {curr_prob:.3f} | {strength} |".format(
                move=float(row["implied_probability_change"]),
                player=row["player_name"],
                market=row["market_type"],
                prev=row["previous_price_american"],
                curr=row["current_price_american"],
                prev_prob=float(row["previous_implied_probability"]),
                curr_prob=float(row["current_implied_probability"]),
                strength=row["movement_strength"],
            )
        )
    return lines


def build_odds_movement_report(
    history_dir: Path,
    output_dir: Path,
    current_snapshot_path: Optional[Path] = None,
    top_n: int = 50,
) -> dict[str, object]:
    previous_snapshot, current_snapshot = select_snapshot_pair(history_dir, current_snapshot_path)
    movement_rows: list[dict[str, object]] = []
    if previous_snapshot is not None and current_snapshot is not None:
        movement_rows = build_movement_rows(read_csv(previous_snapshot), read_csv(current_snapshot))

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "odds_movement.csv", MOVEMENT_COLUMNS, movement_rows)
    (output_dir / "report.md").write_text(
        render_markdown(movement_rows, previous_snapshot, current_snapshot, top_n=top_n),
        encoding="utf-8",
    )
    return {
        "movement_rows": movement_rows,
        "previous_snapshot": previous_snapshot,
        "current_snapshot": current_snapshot,
        "output_dir": output_dir,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="odds-movement")
    parser.add_argument("--history-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--current-snapshot", type=Path)
    parser.add_argument("--top-n", type=int, default=50)
    args = parser.parse_args(argv)

    build_odds_movement_report(
        args.history_dir,
        args.output_dir,
        current_snapshot_path=args.current_snapshot,
        top_n=args.top_n,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
