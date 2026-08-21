"""Build event-round-relative performance rows from canonical round scores."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Optional

ROUND_PERFORMANCE_COLUMNS = [
    "event_id",
    "event_name",
    "event_date_start",
    "event_date_end",
    "season",
    "course_id",
    "player_id",
    "player_name",
    "round_number",
    "score",
    "field_round_score_avg",
    "relative_to_field",
    "event_round_field_size",
]


class RoundPerformanceError(ValueError):
    """Raised when canonical round scores cannot be converted safely."""


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise RoundPerformanceError(f"missing canonical table: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def parse_score(value: object) -> Optional[int]:
    text = str(value or "").strip()
    if not text:
        return None
    return int(float(text))


def build_round_performance_rows(
    events: list[dict[str, str]],
    players: list[dict[str, str]],
    round_scores: list[dict[str, str]],
    min_group_size: int = 2,
    min_score: int = 58,
    max_score: int = 110,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    if min_score >= max_score:
        raise RoundPerformanceError("min_score must be less than max_score")
    event_by_id = {row["event_id"]: row for row in events}
    player_by_id = {row["player_id"]: row for row in players}
    groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    missing_event_rows = 0
    missing_player_rows = 0
    invalid_score_rows = 0
    out_of_range_score_rows = 0

    for row in round_scores:
        event = event_by_id.get(row["event_id"])
        if event is None:
            missing_event_rows += 1
            continue
        player = player_by_id.get(row["player_id"])
        if player is None:
            missing_player_rows += 1
            continue
        try:
            score = parse_score(row.get("score"))
        except ValueError:
            invalid_score_rows += 1
            continue
        if score is None:
            invalid_score_rows += 1
            continue
        if score < min_score or score > max_score:
            out_of_range_score_rows += 1
            continue
        round_number = str(row.get("round_number") or "").strip()
        if not round_number:
            invalid_score_rows += 1
            continue
        groups[(row["event_id"], round_number)].append(
            {
                "source_row": row,
                "event": event,
                "player": player,
                "score": score,
            }
        )

    output: list[dict[str, object]] = []
    small_group_rows = 0
    for (event_id, round_number), group_rows in sorted(
        groups.items(),
        key=lambda item: (
            item[1][0]["event"].get("date_start", ""),
            item[0][0],
            int(item[0][1]),
        ),
    ):
        if len(group_rows) < min_group_size:
            small_group_rows += len(group_rows)
            continue
        field_average = mean(float(row["score"]) for row in group_rows)
        for enriched in sorted(
            group_rows,
            key=lambda row: str(row["player"].get("player_name", "")),
        ):
            source_row = enriched["source_row"]
            event = enriched["event"]
            player = enriched["player"]
            score = int(enriched["score"])
            output.append(
                {
                    "event_id": event_id,
                    "event_name": event.get("event_name", ""),
                    "event_date_start": event.get("date_start", ""),
                    "event_date_end": event.get("date_end") or event.get("date_start", ""),
                    "season": event.get("season", ""),
                    "course_id": source_row.get("course_id", ""),
                    "player_id": source_row["player_id"],
                    "player_name": player.get("player_name", ""),
                    "round_number": int(round_number),
                    "score": score,
                    "field_round_score_avg": round(field_average, 6),
                    "relative_to_field": round(field_average - score, 6),
                    "event_round_field_size": len(group_rows),
                }
            )

    scores = [int(row["score"]) for row in output]
    group_sizes = [len(rows) for rows in groups.values() if len(rows) >= min_group_size]
    summary = {
        "source_round_rows": len(round_scores),
        "performance_rows": len(output),
        "event_round_groups": len(group_sizes),
        "events": len({row["event_id"] for row in output}),
        "players": len({row["player_id"] for row in output}),
        "score_min": min(scores) if scores else None,
        "score_max": max(scores) if scores else None,
        "group_size_min": min(group_sizes) if group_sizes else None,
        "group_size_max": max(group_sizes) if group_sizes else None,
        "missing_event_rows": missing_event_rows,
        "missing_player_rows": missing_player_rows,
        "invalid_score_rows": invalid_score_rows,
        "out_of_range_score_rows": out_of_range_score_rows,
        "small_group_rows_excluded": small_group_rows,
        "min_group_size": min_group_size,
        "min_score": min_score,
        "max_score": max_score,
    }
    return output, summary


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=ROUND_PERFORMANCE_COLUMNS,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def render_report(summary: dict[str, object]) -> str:
    lines = [
        "# Round Performance Build",
        "",
        "Positive relative performance means the player scored better than the",
        "same event-round field average.",
        "",
    ]
    for key, value in summary.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines).rstrip() + "\n"


def build_round_performance(
    input_dir: Path,
    output_path: Path,
    report_path: Optional[Path] = None,
    min_group_size: int = 2,
    min_score: int = 58,
    max_score: int = 110,
) -> dict[str, object]:
    rows, summary = build_round_performance_rows(
        read_csv(input_dir / "events.csv"),
        read_csv(input_dir / "players.csv"),
        read_csv(input_dir / "round_scores.csv"),
        min_group_size=min_group_size,
        min_score=min_score,
        max_score=max_score,
    )
    write_csv(output_path, rows)
    report_path = report_path or output_path.with_suffix(".report.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(summary), encoding="utf-8")
    summary_path = report_path.with_suffix(".json")
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "rows": rows,
        "summary": summary,
        "output_path": output_path,
        "report_path": report_path,
        "summary_path": summary_path,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="build-round-performance")
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report-output", type=Path)
    parser.add_argument("--min-group-size", type=int, default=2)
    parser.add_argument("--min-score", type=int, default=58)
    parser.add_argument("--max-score", type=int, default=110)
    args = parser.parse_args(argv)

    result = build_round_performance(
        args.input_dir,
        args.output,
        report_path=args.report_output,
        min_group_size=args.min_group_size,
        min_score=args.min_score,
        max_score=args.max_score,
    )
    print(f"round_performance_output={result['output_path']}")
    print(f"round_performance_rows={len(result['rows'])}")
    print(f"round_performance_report={result['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
