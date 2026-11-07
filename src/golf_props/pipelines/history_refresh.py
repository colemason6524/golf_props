"""Build and validate a versioned, append-only performance-history refresh.

The refresh never edits the frozen incumbent inputs. It normalizes preserved
final CBS result pages into a new canonical directory, merges them ahead of the
existing canonical tables, rebuilds round-relative performance, and records
every input/output hash in a manifest.
"""

from __future__ import annotations

import csv
import hashlib
from collections import Counter
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from golf_props.analysis.performance_data import write_performance_data_audit
from golf_props.features.round_performance import build_round_performance
from golf_props.normalization.cbs_results import normalize_directory
from golf_props.normalization.merge_results import merge_directories
from golf_props.schemas import COURSE_ALIASES_COLUMNS

FROZEN_PARAMETERS = {
    "half_life_days": 365.0,
    "prior_rounds": 8.0,
    "variance_prior_rounds": 20.0,
}
REQUIRED_TABLES = (
    "events",
    "courses",
    "players",
    "event_courses",
    "player_event_results",
    "round_scores",
)


class HistoryRefreshError(ValueError):
    """Raised when a refresh cannot be built or validated safely."""


@dataclass(frozen=True)
class RefreshPlan:
    base_canonical: Path
    base_round_performance: Path
    add_raw_dir: Path
    output_root: Path
    version: str
    source_cutoff: str
    as_of_date: str
    course_aliases: Path
    parent_manifest: Optional[Path] = None
    excluded_events: list[dict[str, Any]] = field(default_factory=list)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sha256_tree(root: Path) -> dict[str, str]:
    root = Path(root)
    return {
        str(path.relative_to(root)): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def prepare_refresh_raw(
    inventory: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Copy every preserved page and write metadata for included events only."""
    output_dir = Path(output_dir)
    raw_dir = output_dir / "raw"
    excluded_dir = output_dir / "excluded"
    raw_dir.mkdir(parents=True, exist_ok=True)
    excluded_dir.mkdir(parents=True, exist_ok=True)
    metadata_events = []
    excluded = []
    inputs = {}
    for event in inventory.get("events", []):
        source = Path(str(event.get("preserved_page") or ""))
        if not source.is_file():
            excluded.append({**event, "preserve_reason": "preserved_page_missing"})
            continue
        target = raw_dir / source.name
        if target.exists() and _sha256(target) != _sha256(source):
            raise HistoryRefreshError(f"raw filename collision: {target}")
        if not target.exists():
            shutil.copy2(source, target)
        inputs[str(target)] = _sha256(target)
        if event.get("include_candidate"):
            metadata_events.append(
                {
                    "event_name": event["event_name"],
                    "date_start": event["cbs_discovery_start"],
                    "date_end": event["cbs_discovery_end"],
                    "course_name": event["course"],
                    "location": event.get("location", ""),
                    "url": event.get("url", ""),
                    "raw_path": str(target.resolve()),
                    "date_source": "cbs_discovery",
                    "official_start_date": event.get("official_start_date") or "",
                    "official_date_source": event.get("official_date_source") or "",
                }
            )
        else:
            excluded_target = excluded_dir / source.name
            if not excluded_target.exists():
                shutil.copy2(source, excluded_target)
            excluded.append({**event, "preserve_reason": "not_eligible"})
    metadata = {
        "source": "cbs_sports",
        "tour": "PGA",
        "schedule_url": "https://www.cbssports.com/golf/schedules/2026/",
        "as_of_date": inventory.get("as_of"),
        "event_count": len(metadata_events),
        "events": metadata_events,
        "excluded_events": excluded,
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "raw_input_hashes.json").write_text(
        json.dumps(inputs, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return metadata


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def deduplicate_canonical_tables(canonical_dir: Path) -> dict[str, int]:
    """Resolve duplicate ids without silently changing the surviving result.

    A preserved CBS page can list one player in both the CUT and WD sections.
    Keep the row with the most completed rounds, then the non-withdrawn row;
    any remaining ambiguity fails closed.
    """
    canonical_dir = Path(canonical_dir)
    results_path = canonical_dir / "player_event_results.csv"
    rows = _read_csv(results_path)
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["result_id"], []).append(row)
    kept = []
    duplicate_count = 0
    for result_id, group in grouped.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        duplicate_count += len(group) - 1
        ordered = sorted(
            group,
            key=lambda row: (
                int(row.get("rounds_played") or 0),
                row.get("withdrawn") not in {"True", "true", "1"},
                row.get("disqualified") not in {"True", "true", "1"},
            ),
            reverse=True,
        )
        best = ordered[0]
        if len(ordered) > 1:
            for other in ordered[1:]:
                for column in best:
                    if column in {
                        "finish_text",
                        "made_cut",
                        "withdrawn",
                        "disqualified",
                        "total_score",
                        "total_to_par",
                        "rounds_played",
                    }:
                        continue
                    if best[column] != other[column]:
                        raise HistoryRefreshError(
                            f"conflicting duplicate result {result_id}: {column}"
                        )
        kept.append(best)
    _write_csv(results_path, kept)
    rounds_path = canonical_dir / "round_scores.csv"
    rounds = _read_csv(rounds_path)
    round_groups: dict[str, list[dict[str, str]]] = {}
    for row in rounds:
        round_groups.setdefault(row["round_score_id"], []).append(row)
    kept_rounds = []
    round_duplicates = 0
    for round_id, group in round_groups.items():
        if len(group) == 1:
            kept_rounds.append(group[0])
            continue
        round_duplicates += len(group) - 1
        if any(row != group[0] for row in group[1:]):
            raise HistoryRefreshError(f"conflicting duplicate round score {round_id}")
        kept_rounds.append(group[0])
    _write_csv(rounds_path, kept_rounds)
    return {
        "player_event_results": duplicate_count,
        "round_scores": round_duplicates,
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise HistoryRefreshError(f"missing table: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def filter_course_aliases(
    aliases_path: Path,
    base_courses: Path,
    add_courses: Path,
    output_path: Path,
) -> int:
    """Keep only reviewed mappings whose source identity exists in this merge.

    ``merge_directories`` validates every accepted crosswalk row against the
    courses being merged. Historical canonical directories already store
    remapped course ids, so a refresh merge must not re-apply aliases for source
    identities that are no longer present.
    """
    available = {
        (row.get("source", ""), row.get("source_course_id", ""))
        for path in (base_courses, add_courses)
        for row in _read_csv(path)
    }
    with Path(aliases_path).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    kept = [
        row
        for row in rows
        if (row.get("source", ""), row.get("source_course_id", "")) in available
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with Path(output_path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COURSE_ALIASES_COLUMNS)
        writer.writeheader()
        writer.writerows(kept)
    return len(kept)


def duplicate_ids(canonical_dir: Path) -> dict[str, set[str]]:
    canonical_dir = Path(canonical_dir)
    result_ids = [row["result_id"] for row in _read_csv(canonical_dir / "player_event_results.csv")]
    round_ids = [row["round_score_id"] for row in _read_csv(canonical_dir / "round_scores.csv")]
    event_ids = [row["event_id"] for row in _read_csv(canonical_dir / "events.csv")]
    def seen(values: list[str]) -> set[str]:
        return {value for value, count in Counter(values).items() if count > 1}

    return {
        "events": seen(event_ids),
        "player_event_results": seen(result_ids),
        "round_scores": seen(round_ids),
    }


def validate_refresh(
    canonical_dir: Path,
    round_performance_path: Path,
    *,
    as_of_date: str,
    expected_events: Optional[int] = None,
    allowed_duplicate_ids: Optional[dict[str, set[str]]] = None,
    allowed_out_of_range_round_ids: Optional[set[str]] = None,
) -> dict[str, Any]:
    canonical_dir = Path(canonical_dir)
    for table in REQUIRED_TABLES:
        if not (canonical_dir / f"{table}.csv").exists():
            raise HistoryRefreshError(f"missing canonical table: {table}.csv")
    events = _read_csv(canonical_dir / "events.csv")
    results = _read_csv(canonical_dir / "player_event_results.csv")
    rounds = _read_csv(canonical_dir / "round_scores.csv")
    event_ids = [row["event_id"] for row in events]
    result_ids = [row["result_id"] for row in results]
    round_ids = [row["round_score_id"] for row in rounds]
    def seen(values: list[str]) -> set[str]:
        return {value for value, count in Counter(values).items() if count > 1}

    duplicate_sets = {
        "events": seen(event_ids),
        "player_event_results": seen(result_ids),
        "round_scores": seen(round_ids),
    }
    allowed = allowed_duplicate_ids or {}
    new_duplicates = {
        table: sorted(ids - allowed.get(table, set()))
        for table, ids in duplicate_sets.items()
    }
    if any(new_duplicates.values()):
        raise HistoryRefreshError(
            f"refresh introduced duplicate canonical ids: {new_duplicates}"
        )
    duplicates = {
        table: len(ids) for table, ids in duplicate_sets.items()
    }
    bad_dates = [
        row["event_id"]
        for row in events
        if not row.get("date_start")
        or not row.get("date_end")
        or row["date_start"] > row["date_end"]
    ]
    if bad_dates:
        raise HistoryRefreshError(f"invalid event dates: {bad_dates[:5]}")
    future = [
        row["event_id"]
        for row in events
        if row.get("date_end") and row["date_end"] >= as_of_date
    ]
    if future:
        raise HistoryRefreshError(
            f"events completed on/after as-of date would leak into history: {future[:5]}"
        )
    out_of_range_ids = []
    for row in rounds:
        try:
            score = int(row["score"])
        except (TypeError, ValueError) as exc:
            raise HistoryRefreshError(
                f"non-integer round score for {row.get('round_score_id')}"
            ) from exc
        if score < 58 or score > 110:
            out_of_range_ids.append(row["round_score_id"])
    allowed_out_of_range = allowed_out_of_range_round_ids or set()
    new_out_of_range = [
        round_id for round_id in out_of_range_ids if round_id not in allowed_out_of_range
    ]
    if new_out_of_range:
        raise HistoryRefreshError(
            f"refresh introduced out-of-range round scores: {new_out_of_range[:5]}"
        )
    if expected_events is not None and len(events) < expected_events:
        raise HistoryRefreshError(
            f"refreshed bundle has {len(events)} events; expected at least {expected_events}"
        )
    feature_rows = _read_csv(round_performance_path)
    if not feature_rows:
        raise HistoryRefreshError("round-performance feature file is empty")
    return {
        "events": len(events),
        "event_courses": len(_read_csv(canonical_dir / "event_courses.csv")),
        "players": len(_read_csv(canonical_dir / "players.csv")),
        "player_event_results": len(results),
        "round_scores": len(rounds),
        "round_performance_rows": len(feature_rows),
        "latest_event_start": max(row["date_start"] for row in events),
        "latest_event_end": max(row["date_end"] for row in events),
        "duplicates": duplicates,
        "out_of_range_rounds": len(out_of_range_ids),
        "new_out_of_range_rounds": 0,
        "future_events": 0,
    }


def build_history_refresh(plan: RefreshPlan) -> dict[str, Any]:
    output_root = Path(plan.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    add_canonical = output_root / "canonical_add"
    normalize_directory(Path(plan.add_raw_dir), add_canonical)
    add_deduplicated = deduplicate_canonical_tables(add_canonical)
    base_duplicates = duplicate_ids(Path(plan.base_canonical))
    base_out_of_range = {
        row["round_score_id"]
        for row in _read_csv(Path(plan.base_canonical) / "round_scores.csv")
        if int(row["score"]) < 58 or int(row["score"]) > 110
    }
    canonical_dir = output_root / "canonical"
    applicable_aliases = output_root / "course_aliases_applicable.csv"
    alias_count = filter_course_aliases(
        Path(plan.course_aliases),
        Path(plan.base_canonical) / "courses.csv",
        add_canonical / "courses.csv",
        applicable_aliases,
    )
    merged = merge_directories(
        Path(plan.base_canonical),
        add_canonical,
        canonical_dir,
        course_aliases_path=applicable_aliases,
    )
    round_performance = output_root / "round_performance.csv"
    build_round_performance(
        canonical_dir,
        round_performance,
        report_path=output_root / "round_performance_report.md",
    )
    audit = write_performance_data_audit(canonical_dir, output_root / "audit")
    validation = validate_refresh(
        canonical_dir,
        round_performance,
        as_of_date=plan.as_of_date,
        expected_events=len(merged["events"]),
        allowed_duplicate_ids=base_duplicates,
        allowed_out_of_range_round_ids=base_out_of_range,
    )
    parent = None
    if plan.parent_manifest:
        parent_path = Path(plan.parent_manifest)
        parent = {
            "path": str(parent_path),
            "sha256": _sha256(parent_path),
        }
    manifest = {
        "schema_version": 1,
        "version": plan.version,
        "status": "candidate_awaiting_activation",
        "created_at_utc": _utc_now(),
        "source_cutoff": plan.source_cutoff,
        "as_of_date": plan.as_of_date,
        "base_canonical": str(plan.base_canonical),
        "base_round_performance": str(plan.base_round_performance),
        "add_raw_dir": str(plan.add_raw_dir),
        "course_aliases": str(plan.course_aliases),
        "parent_manifest": parent,
        "course_aliases_applicable": str(applicable_aliases),
        "course_aliases_applicable_sha256": _sha256(applicable_aliases),
        "course_aliases_applicable_rows": alias_count,
        "frozen_parameters": dict(FROZEN_PARAMETERS),
        "frozen_parameters_changed": False,
        "excluded_events": plan.excluded_events,
        "add_deduplicated": add_deduplicated,
        "pre_existing_base_duplicate_ids": {
            table: len(ids) for table, ids in base_duplicates.items()
        },
        "validation": validation,
        "audit": {
            "summary": str(audit["summary_path"]),
            "summary_sha256": _sha256(audit["summary_path"]),
            "report": str(audit["report_path"]),
            "report_sha256": _sha256(audit["report_path"]),
        },
        "outputs": {
            "canonical_dir": str(canonical_dir),
            "canonical_hashes": _sha256_tree(canonical_dir),
            "round_performance": str(round_performance),
            "round_performance_sha256": _sha256(round_performance),
        },
        "production_effect": "none",
    }
    manifest_path = output_root / "refresh_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
