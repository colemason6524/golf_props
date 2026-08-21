"""Build event-level player ranking cards from prediction rows."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Optional

TARGET_SPECS = {
    "target_make_cut": "make_cut",
    "target_top20": "top20",
    "target_top10": "top10",
    "target_top5": "top5",
}

IDENTITY_COLUMNS = [
    "event_id",
    "event_name",
    "event_date_start",
    "season",
    "course_id",
    "course_name",
    "player_id",
    "player_name",
    "model_type",
]

RANKING_COLUMNS = IDENTITY_COLUMNS + [
    "winner_prob",
    "winner_actual",
    "winner_rank",
    "make_cut_prob",
    "make_cut_actual",
    "make_cut_rank",
    "top20_prob",
    "top20_actual",
    "top20_rank",
    "top10_prob",
    "top10_actual",
    "top10_rank",
    "top5_prob",
    "top5_actual",
    "top5_rank",
]


class EventRankingError(ValueError):
    """Raised when prediction rows cannot be converted into event rankings."""


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise EventRankingError(f"missing predictions file: {path}")
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


def format_probability(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{value:.3f}"


def build_ranking_rows(prediction_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], dict[str, object]] = {}

    for row in prediction_rows:
        target = row.get("target")
        if target not in TARGET_SPECS:
            continue
        short = TARGET_SPECS[target]
        key = (row["event_id"], row["player_id"])
        record = grouped.setdefault(
            key,
            {
                "event_id": row["event_id"],
                "event_name": row.get("event_name", ""),
                "event_date_start": row.get("event_date_start", ""),
                "season": row.get("season", ""),
                "course_id": row.get("course_id", ""),
                "course_name": row.get("course_name", ""),
                "player_id": row["player_id"],
                "player_name": row.get("player_name", ""),
                "model_type": row.get("model_type", ""),
            },
        )
        record[f"{short}_prob"] = parse_float(row.get("model_prob"))
        record[f"{short}_actual"] = row.get("actual", "")

    ranking_rows = []
    for record in grouped.values():
        full = {column: None for column in RANKING_COLUMNS}
        full.update(record)
        ranking_rows.append(full)

    add_event_ranks(ranking_rows)
    return sorted(
        ranking_rows,
        key=lambda row: (
            str(row["event_date_start"]),
            str(row["event_name"]),
            int(row["top20_rank"] or 999999),
            str(row["player_name"]),
        ),
    )


def add_event_ranks(rows: list[dict[str, object]]) -> None:
    rows_by_event: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        rows_by_event[str(row["event_id"])].append(row)

    for event_rows in rows_by_event.values():
        for short in ["winner", "make_cut", "top20", "top10", "top5"]:
            ranked = sorted(
                [row for row in event_rows if row.get(f"{short}_prob") is not None],
                key=lambda row: (-float(row[f"{short}_prob"]), str(row["player_name"])),
            )
            previous_prob: Optional[float] = None
            previous_rank = 0
            for index, row in enumerate(ranked, start=1):
                prob = float(row[f"{short}_prob"])
                rank = previous_rank if previous_prob == prob else index
                row[f"{short}_rank"] = rank
                previous_prob = prob
                previous_rank = rank


def render_markdown(
    ranking_rows: list[dict[str, object]],
    max_events: int,
    top_n: int,
) -> str:
    lines = ["# Event Ranking Report", ""]
    events: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in ranking_rows:
        events[str(row["event_id"])].append(row)

    ordered_events = sorted(
        events.values(),
        key=lambda rows: (str(rows[0]["event_date_start"]), str(rows[0]["event_name"])),
    )
    if max_events > 0:
        ordered_events = ordered_events[-max_events:]

    for event_rows in ordered_events:
        first = event_rows[0]
        lines.extend(
            [
                f"## {first['event_date_start']} - {first['event_name']}",
                "",
                f"Course: {first['course_name']}",
                "",
            ]
        )
        for short, label in [
            ("winner", "Winner"),
            ("make_cut", "Make Cut"),
            ("top20", "Top 20"),
            ("top10", "Top 10"),
            ("top5", "Top 5"),
        ]:
            ranked = sorted(
                [row for row in event_rows if row.get(f"{short}_rank")],
                key=lambda row: (int(row[f"{short}_rank"]), str(row["player_name"])),
            )[:top_n]
            lines.extend(
                [
                    f"### {label}",
                    "",
                    "| Rank | Player | Prob | Actual |",
                    "|---:|---|---:|---:|",
                ]
            )
            for row in ranked:
                lines.append(
                    "| {rank} | {player} | {prob} | {actual} |".format(
                        rank=row[f"{short}_rank"],
                        player=row["player_name"],
                        prob=format_probability(parse_float(row.get(f"{short}_prob"))),
                        actual=row.get(f"{short}_actual") or "",
                    )
                )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_event_rankings(
    predictions_path: Path,
    output_dir: Path,
    max_events: int = 10,
    top_n: int = 20,
) -> dict[str, list[dict[str, object]]]:
    prediction_rows = read_csv(predictions_path)
    ranking_rows = build_ranking_rows(prediction_rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "event_rankings.csv", RANKING_COLUMNS, ranking_rows)
    (output_dir / "report.md").write_text(
        render_markdown(ranking_rows, max_events=max_events, top_n=top_n),
        encoding="utf-8",
    )

    return {"rankings": ranking_rows}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="event-rankings")
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-events", type=int, default=10)
    parser.add_argument("--top-n", type=int, default=20)
    args = parser.parse_args(argv)

    build_event_rankings(
        args.predictions,
        args.output_dir,
        max_events=args.max_events,
        top_n=args.top_n,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
