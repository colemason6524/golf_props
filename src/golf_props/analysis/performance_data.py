"""Audit canonical PGA performance data before model development."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Optional

from golf_props.features.player_event import (
    parse_bool,
    parse_int,
    target_at_or_better,
)

REQUIRED_TABLES = [
    "events",
    "courses",
    "players",
    "event_courses",
    "player_event_results",
    "round_scores",
]


class PerformanceDataAuditError(ValueError):
    """Raised when canonical performance data cannot be audited."""


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise PerformanceDataAuditError(f"missing canonical table: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def finish_target(
    row: dict[str, str],
    threshold: int,
) -> Optional[bool]:
    finish_position = parse_int(row.get("finish_position", ""))
    made_cut = parse_bool(row.get("made_cut", ""))
    withdrawn = parse_bool(row.get("withdrawn", "")) or False
    disqualified = parse_bool(row.get("disqualified", "")) or False
    return target_at_or_better(
        finish_position,
        threshold,
        made_cut,
        withdrawn,
        disqualified,
    )


def rate_summary(values: list[Optional[bool]]) -> dict[str, object]:
    eligible = [value for value in values if value is not None]
    positives = sum(1 for value in eligible if value)
    return {
        "eligible_rows": len(eligible),
        "positive_rows": positives,
        "positive_rate": round(positives / len(eligible), 6) if eligible else None,
    }


def distribution_summary(values: list[int]) -> dict[str, object]:
    if not values:
        return {"min": None, "median": None, "max": None}
    return {
        "min": min(values),
        "median": float(median(values)),
        "max": max(values),
    }


def audit_performance_data(input_dir: Path) -> dict[str, object]:
    tables = {
        name: read_csv(input_dir / f"{name}.csv") for name in REQUIRED_TABLES
    }
    events = tables["events"]
    players = tables["players"]
    event_courses = tables["event_courses"]
    results = tables["player_event_results"]
    rounds = tables["round_scores"]

    event_ids = {row["event_id"] for row in events}
    player_ids = {row["player_id"] for row in players}
    mapped_event_ids = {row["event_id"] for row in event_courses}
    result_counts = Counter(row["event_id"] for row in results)
    player_start_counts = Counter(row["player_id"] for row in results)
    dates = sorted(row["date_start"] for row in events if row.get("date_start"))
    field_sizes = list(result_counts.values())
    events_without_results = [
        {
            "event_id": row["event_id"],
            "event_name": row.get("event_name", ""),
            "date_start": row.get("date_start", ""),
        }
        for row in events
        if row["event_id"] not in result_counts
    ]

    made_cut_values = [
        parse_bool(row.get("made_cut", "")) for row in results
    ]
    targets = {
        "make_cut": rate_summary(made_cut_values),
        "top20": rate_summary([finish_target(row, 20) for row in results]),
        "top10": rate_summary([finish_target(row, 10) for row in results]),
        "top5": rate_summary([finish_target(row, 5) for row in results]),
        "winner": rate_summary([finish_target(row, 1) for row in results]),
    }

    summary: dict[str, object] = {
        "input_dir": str(input_dir),
        "table_rows": {name: len(rows) for name, rows in tables.items()},
        "date_range": {
            "first_event": dates[0] if dates else None,
            "last_event": dates[-1] if dates else None,
        },
        "event_coverage": {
            "events_with_results": len(result_counts),
            "events_without_results": len(events_without_results),
            "events_without_result_rows": events_without_results,
            "events_without_course_mapping": len(event_ids - mapped_event_ids),
            "field_size": distribution_summary(field_sizes),
        },
        "result_quality": {
            "orphan_event_rows": sum(
                1 for row in results if row["event_id"] not in event_ids
            ),
            "orphan_player_rows": sum(
                1 for row in results if row["player_id"] not in player_ids
            ),
            "missing_finish_position_rows": sum(
                1 for row in results if not row.get("finish_position")
            ),
            "withdrawn_rows": sum(
                1
                for row in results
                if parse_bool(row.get("withdrawn", "")) is True
            ),
            "disqualified_rows": sum(
                1
                for row in results
                if parse_bool(row.get("disqualified", "")) is True
            ),
            "round_rows_per_result": (
                round(len(rounds) / len(results), 6) if results else None
            ),
        },
        "player_history": {
            "players_with_results": len(player_start_counts),
            "players_with_3_plus_starts": sum(
                1 for starts in player_start_counts.values() if starts >= 3
            ),
            "starts_per_player": distribution_summary(
                list(player_start_counts.values())
            ),
        },
        "targets": targets,
    }
    return summary


def render_markdown(summary: dict[str, object]) -> str:
    table_rows = summary["table_rows"]
    date_range = summary["date_range"]
    event_coverage = summary["event_coverage"]
    result_quality = summary["result_quality"]
    player_history = summary["player_history"]
    targets = summary["targets"]
    assert isinstance(table_rows, dict)
    assert isinstance(date_range, dict)
    assert isinstance(event_coverage, dict)
    assert isinstance(result_quality, dict)
    assert isinstance(player_history, dict)
    assert isinstance(targets, dict)

    lines = [
        "# Performance Data Audit",
        "",
        f"canonical_input: {summary['input_dir']}",
        f"event_date_range: {date_range['first_event']} to {date_range['last_event']}",
        "",
        "## Canonical Tables",
        "",
        "| Table | Rows |",
        "|---|---:|",
    ]
    for name, count in table_rows.items():
        lines.append(f"| {name} | {count} |")

    field_size = event_coverage["field_size"]
    starts = player_history["starts_per_player"]
    assert isinstance(field_size, dict)
    assert isinstance(starts, dict)
    lines.extend(
        [
            "",
            "## Coverage",
            "",
            f"- Events with results: {event_coverage['events_with_results']}",
            f"- Events without results: {event_coverage['events_without_results']}",
            f"- Events without course mapping: {event_coverage['events_without_course_mapping']}",
            (
                "- Field size min/median/max: "
                f"{field_size['min']} / {field_size['median']} / {field_size['max']}"
            ),
            f"- Players with results: {player_history['players_with_results']}",
            f"- Players with 3+ starts: {player_history['players_with_3_plus_starts']}",
            (
                "- Starts per player min/median/max: "
                f"{starts['min']} / {starts['median']} / {starts['max']}"
            ),
            f"- Round rows per result: {result_quality['round_rows_per_result']}",
            "",
            "## Target Availability",
            "",
            "| Target | Eligible | Positive | Rate |",
            "|---|---:|---:|---:|",
        ]
    )
    for target, values in targets.items():
        assert isinstance(values, dict)
        rate = values["positive_rate"]
        lines.append(
            f"| {target} | {values['eligible_rows']} | "
            f"{values['positive_rows']} | {rate if rate is not None else ''} |"
        )

    warnings = []
    for label in [
        "orphan_event_rows",
        "orphan_player_rows",
    ]:
        if result_quality[label]:
            warnings.append(f"{label}: {result_quality[label]}")
    if event_coverage["events_without_course_mapping"]:
        warnings.append(
            "events_without_course_mapping: "
            f"{event_coverage['events_without_course_mapping']}"
        )
    if event_coverage["events_without_results"]:
        missing_events = event_coverage["events_without_result_rows"]
        assert isinstance(missing_events, list)
        event_labels = ", ".join(
            f"{row['event_name']} ({row['date_start']})"
            for row in missing_events
            if isinstance(row, dict)
        )
        warnings.append(
            f"events_without_results: {event_coverage['events_without_results']}"
            + (f" — {event_labels}" if event_labels else "")
        )
    lines.extend(["", "## Warnings", ""])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("No event, referential-integrity, or course-mapping warnings.")
    return "\n".join(lines).rstrip() + "\n"


def write_performance_data_audit(
    input_dir: Path,
    output_dir: Path,
) -> dict[str, object]:
    summary = audit_performance_data(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.json"
    report_path = output_dir / "report.md"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(render_markdown(summary), encoding="utf-8")
    return {
        "summary": summary,
        "summary_path": summary_path,
        "report_path": report_path,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="audit-performance-data")
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    result = write_performance_data_audit(args.input_dir, args.output_dir)
    print(f"performance_data_summary={result['summary_path']}")
    print(f"performance_data_report={result['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
