"""Run the DraftKings current golf value workflow."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from golf_props.backtest.current_event_rankings import build_current_event_rankings
from golf_props.backtest.value_report import build_value_report
from golf_props.config import INTERIM_DIR, PROCESSED_DIR, RAW_DIR
from golf_props.odds.draftkings_predictions import (
    DEFAULT_MAX_LINKED_PAGES,
    DEFAULT_RETRY_SLEEP_SECONDS,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_URL,
    collect_and_parse,
)
from golf_props.odds.movement import build_odds_movement_report

DEFAULT_FEATURES_PATH = INTERIM_DIR / "features" / "pga_2001_2026_player_event_features.csv"
DEFAULT_RAW_OUTPUT_DIR = RAW_DIR / "odds_snapshots" / "draftkings_predictions_golf_placement"
DEFAULT_ODDS_OUTPUT = PROCESSED_DIR / "odds_snapshots" / "draftkings_golf_placement_latest.csv"
DEFAULT_ODDS_HISTORY_DIR = PROCESSED_DIR / "odds_snapshots" / "history"
DEFAULT_RANKINGS_OUTPUT_DIR = INTERIM_DIR / "reports" / "dk_golf_placement_current_event_rankings"
DEFAULT_VALUE_OUTPUT_DIR = INTERIM_DIR / "reports" / "dk_golf_placement_current_value_report"
DEFAULT_MOVEMENT_OUTPUT_DIR = INTERIM_DIR / "reports" / "dk_golf_placement_odds_movement"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def timestamp_slug(value: str) -> str:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
        return iso_utc(parsed).replace("-", "").replace(":", "")
    except ValueError:
        return value.replace("-", "").replace(":", "").replace(".", "").replace("+0000", "Z")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def odds_snapshot_timestamp(odds_output: Path, fallback: datetime) -> str:
    rows = read_csv_rows(odds_output)
    captured_values = sorted(
        row.get("captured_at_utc", "").strip()
        for row in rows
        if row.get("captured_at_utc", "").strip()
    )
    if captured_values:
        return captured_values[-1]
    return iso_utc(fallback)


def snapshot_processed_odds(odds_output: Path, history_dir: Path, fallback_time: datetime) -> Optional[Path]:
    if not odds_output.exists():
        return None
    captured_at = odds_snapshot_timestamp(odds_output, fallback_time)
    history_dir.mkdir(parents=True, exist_ok=True)
    output = history_dir / f"dk_golf_placement_{timestamp_slug(captured_at)}.csv"
    shutil.copyfile(odds_output, output)
    return output


def write_run_metadata(
    output: Path,
    metadata: dict[str, object],
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def run_dk_current_value(
    features_path: Path = DEFAULT_FEATURES_PATH,
    raw_output_dir: Path = DEFAULT_RAW_OUTPUT_DIR,
    odds_output: Path = DEFAULT_ODDS_OUTPUT,
    odds_history_dir: Path = DEFAULT_ODDS_HISTORY_DIR,
    rankings_output_dir: Path = DEFAULT_RANKINGS_OUTPUT_DIR,
    value_output_dir: Path = DEFAULT_VALUE_OUTPUT_DIR,
    movement_output_dir: Path = DEFAULT_MOVEMENT_OUTPUT_DIR,
    run_metadata_output: Optional[Path] = None,
    url: str = DEFAULT_URL,
    season: Optional[str] = None,
    event_date: Optional[str] = None,
    course_name: str = "",
    min_prior_starts: int = 3,
    top_n: int = 50,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    retry_sleep_seconds: float = DEFAULT_RETRY_SLEEP_SECONDS,
    max_linked_pages: int = DEFAULT_MAX_LINKED_PAGES,
    skip_collect: bool = False,
    save_odds_history: bool = True,
    build_movement: bool = True,
) -> dict[str, object]:
    run_started_at = utc_now()
    odds_rows = []
    if not skip_collect:
        odds_rows = collect_and_parse(
            raw_output_dir,
            odds_output,
            url=url,
            season=season,
            timeout_seconds=timeout_seconds,
            retries=retries,
            retry_sleep_seconds=retry_sleep_seconds,
            crawl_linked=True,
            max_linked_pages=max_linked_pages,
        )
    odds_file_rows = read_csv_rows(odds_output)
    odds_history_path = (
        snapshot_processed_odds(odds_output, odds_history_dir, run_started_at)
        if save_odds_history
        else None
    )

    ranking_result = build_current_event_rankings(
        features_path,
        odds_output,
        rankings_output_dir,
        event_date=event_date,
        course_name=course_name,
        min_prior_starts=min_prior_starts,
        top_n=top_n,
    )
    value_result = build_value_report(
        rankings_output_dir / "event_rankings.csv",
        odds_output,
        value_output_dir,
        top_n=top_n,
    )
    movement_result = (
        build_odds_movement_report(
            odds_history_dir,
            movement_output_dir,
            current_snapshot_path=odds_history_path,
            top_n=top_n,
        )
        if build_movement and save_odds_history
        else {
            "movement_rows": [],
            "previous_snapshot": None,
            "current_snapshot": odds_history_path,
            "output_dir": movement_output_dir,
        }
    )
    metadata_path = run_metadata_output or value_output_dir / "run_metadata.json"
    run_completed_at = utc_now()
    metadata = {
        "run_started_at_utc": iso_utc(run_started_at),
        "run_completed_at_utc": iso_utc(run_completed_at),
        "features_path": str(features_path),
        "raw_output_dir": str(raw_output_dir),
        "odds_output": str(odds_output),
        "odds_history_path": str(odds_history_path) if odds_history_path else "",
        "rankings_output_dir": str(rankings_output_dir),
        "value_output_dir": str(value_output_dir),
        "movement_output_dir": str(movement_output_dir),
        "url": url,
        "season": season or "",
        "event_date": event_date or "",
        "course_name": course_name,
        "min_prior_starts": min_prior_starts,
        "top_n": top_n,
        "timeout_seconds": timeout_seconds,
        "retries": retries,
        "retry_sleep_seconds": retry_sleep_seconds,
        "max_linked_pages": max_linked_pages,
        "skip_collect": skip_collect,
        "save_odds_history": save_odds_history,
        "build_movement": build_movement,
        "collected_odds_rows": len(odds_rows),
        "odds_file_rows": len(odds_file_rows),
        "ranking_rows": len(ranking_result["rankings"]),
        "value_rows": len(value_result["value_rows"]),
        "movement_rows": len(movement_result["movement_rows"]),
        "unmatched_player_count": len(ranking_result["unmatched_players"]),
        "unmatched_players": ranking_result["unmatched_players"],
        "rankings_csv": str(rankings_output_dir / "event_rankings.csv"),
        "rankings_report": str(rankings_output_dir / "report.md"),
        "value_csv": str(value_output_dir / "value_report.csv"),
        "value_report": str(value_output_dir / "report.md"),
        "movement_csv": str(movement_output_dir / "odds_movement.csv"),
        "movement_report": str(movement_output_dir / "report.md"),
        "movement_previous_snapshot": str(movement_result["previous_snapshot"] or ""),
        "movement_current_snapshot": str(movement_result["current_snapshot"] or ""),
    }
    write_run_metadata(metadata_path, metadata)
    return {
        "odds_rows": odds_rows,
        "rankings": ranking_result["rankings"],
        "unmatched_players": ranking_result["unmatched_players"],
        "value_rows": value_result["value_rows"],
        "odds_output": odds_output,
        "odds_history_path": odds_history_path,
        "rankings_output_dir": rankings_output_dir,
        "value_output_dir": value_output_dir,
        "movement_output_dir": movement_output_dir,
        "run_metadata_path": metadata_path,
        "movement_rows": movement_result["movement_rows"],
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="run-dk-current-value")
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES_PATH)
    parser.add_argument("--raw-output-dir", type=Path, default=DEFAULT_RAW_OUTPUT_DIR)
    parser.add_argument("--odds-output", type=Path, default=DEFAULT_ODDS_OUTPUT)
    parser.add_argument("--odds-history-dir", type=Path, default=DEFAULT_ODDS_HISTORY_DIR)
    parser.add_argument("--rankings-output-dir", type=Path, default=DEFAULT_RANKINGS_OUTPUT_DIR)
    parser.add_argument("--value-output-dir", type=Path, default=DEFAULT_VALUE_OUTPUT_DIR)
    parser.add_argument("--movement-output-dir", type=Path, default=DEFAULT_MOVEMENT_OUTPUT_DIR)
    parser.add_argument("--run-metadata-output", type=Path)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--season")
    parser.add_argument("--event-date")
    parser.add_argument("--course-name", default="")
    parser.add_argument("--min-prior-starts", type=int, default=3)
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument("--retry-sleep-seconds", type=float, default=DEFAULT_RETRY_SLEEP_SECONDS)
    parser.add_argument("--max-linked-pages", type=int, default=DEFAULT_MAX_LINKED_PAGES)
    parser.add_argument("--skip-collect", action="store_true")
    parser.add_argument("--no-save-odds-history", action="store_true")
    parser.add_argument("--no-build-movement", action="store_true")
    args = parser.parse_args(argv)

    result = run_dk_current_value(
        features_path=args.features,
        raw_output_dir=args.raw_output_dir,
        odds_output=args.odds_output,
        odds_history_dir=args.odds_history_dir,
        rankings_output_dir=args.rankings_output_dir,
        value_output_dir=args.value_output_dir,
        movement_output_dir=args.movement_output_dir,
        run_metadata_output=args.run_metadata_output,
        url=args.url,
        season=args.season,
        event_date=args.event_date,
        course_name=args.course_name,
        min_prior_starts=args.min_prior_starts,
        top_n=args.top_n,
        timeout_seconds=args.timeout_seconds,
        retries=args.retries,
        retry_sleep_seconds=args.retry_sleep_seconds,
        max_linked_pages=args.max_linked_pages,
        skip_collect=args.skip_collect,
        save_odds_history=not args.no_save_odds_history,
        build_movement=not args.no_build_movement,
    )
    print(f"odds_output={result['odds_output']}")
    print(f"odds_history_path={result['odds_history_path']}")
    print(f"rankings_output_dir={result['rankings_output_dir']}")
    print(f"value_output_dir={result['value_output_dir']}")
    print(f"movement_output_dir={result['movement_output_dir']}")
    print(f"run_metadata_path={result['run_metadata_path']}")
    print(f"ranking_rows={len(result['rankings'])}")
    print(f"value_rows={len(result['value_rows'])}")
    print(f"movement_rows={len(result['movement_rows'])}")
    print(f"unmatched_players={len(result['unmatched_players'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
