"""Assess whether the active performance history is stale.

The comparison is between the authoritative completed-event schedule and the
events actually present in the active canonical directory. Missing history is
reported explicitly; it is never inferred from a silent date gap.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Optional

from golf_props.events.auto_structure import DECISION_INCLUDE, classify_event
from golf_props.ingestion.cbs_results import extract_schedule_events

STATUS_FRESH = "fresh"
STATUS_STALE = "stale"
STATUS_UNKNOWN = "unknown"


class HistoryFreshnessError(ValueError):
    """Raised when freshness cannot be assessed from the supplied evidence."""


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise HistoryFreshnessError(f"missing table: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _event_key(value: object) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"\([^)]*\)", " ", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def _sha256(path: Optional[Path]) -> str:
    if not path or not Path(path).exists():
        return ""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _schedule_event_id(url: object) -> str:
    match = re.search(r"/(\d+)/", str(url or ""))
    return match.group(1) if match else ""


def _manifest_info(manifest_path: Optional[Path]) -> dict[str, Any]:
    if not manifest_path or not Path(manifest_path).exists():
        return {
            "active_manifest": "",
            "active_manifest_sha256": "",
            "source_data_through": "",
            "created_at_utc": "",
        }
    try:
        data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoryFreshnessError(
            f"invalid frozen manifest: {manifest_path}"
        ) from exc
    frozen = (
        data.get("frozen_parameters")
        or data.get("parameters")
        or data.get("frozen_model")
        or {}
    )
    return {
        "active_manifest": str(manifest_path),
        "active_manifest_sha256": _sha256(Path(manifest_path)),
        "source_data_through": str(
            frozen.get("source_data_through") or data.get("source_data_through") or ""
        ),
        "created_at_utc": str(data.get("created_at_utc") or ""),
    }


def _candidate_refresh(
    canonical_dir: Optional[Path],
) -> Optional[dict[str, Any]]:
    if not canonical_dir:
        return None
    root = Path(canonical_dir).parent
    candidates = []
    for search_root in (root / "history_refresh", root):
        candidates.extend(sorted(search_root.glob("*/refresh_manifest.json")))
    if not candidates:
        return None
    path = candidates[-1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return {
        "path": str(path),
        "version": data.get("version"),
        "status": data.get("status"),
        "latest_event_end": (data.get("validation") or {}).get("latest_event_end"),
        "excluded_events": [
            item.get("event_name") for item in data.get("excluded_events", [])
        ],
        "sha256": _sha256(path),
    }


def assess_history_freshness(
    *,
    canonical_dir: Path,
    schedule_path: Path,
    as_of_date: str,
    frozen_manifest: Optional[Path] = None,
) -> dict[str, Any]:
    """Return a health-ready freshness assessment.

    ``as_of_date`` must be the forecast/decision date. Only events with
    ``date_end < as_of_date`` are eligible: an event ending on the as-of date is
    not treated as completed for point-in-time history.
    """
    canonical_dir = Path(canonical_dir)
    schedule_path = Path(schedule_path)
    if not schedule_path.exists():
        return {
            "schema_version": 1,
            "status": STATUS_UNKNOWN,
            "reason": f"schedule_missing:{schedule_path}",
            "as_of_date": as_of_date,
            "latest_completed_eligible_event": None,
            "latest_included_event": None,
            "missing_events": [],
            "missing_immediately_preceding": None,
            **_manifest_info(frozen_manifest),
            "candidate_refresh": _candidate_refresh(canonical_dir),
        }
    if not (canonical_dir / "events.csv").exists():
        raise HistoryFreshnessError(f"missing canonical events: {canonical_dir}")
    canonical_events = _read_csv(canonical_dir / "events.csv")
    canonical_ids = {
        str(row.get("source_event_id") or "") for row in canonical_events
    }
    canonical_names = {
        (_event_key(row.get("event_name")), str(row.get("season") or ""))
        for row in canonical_events
    }
    schedule_events = extract_schedule_events(
        schedule_path.read_text(encoding="utf-8"),
        as_of_date=date.fromisoformat(as_of_date),
    )
    completed = [
        event
        for event in schedule_events
        if str(event["date_end"]) < as_of_date
    ]
    eligible = []
    excluded = []
    for event in completed:
        decision = classify_event(
            str(event["event_name"]),
            int(str(event["date_start"])[:4]),
            None,
            source_event_id=_schedule_event_id(event.get("url")),
        )
        if decision.get("decision") == DECISION_INCLUDE:
            eligible.append(event)
        else:
            excluded.append(
                {
                    "event_name": event["event_name"],
                    "date_end": event["date_end"],
                    "reason": decision.get("reason", "excluded_format"),
                }
            )
    if not eligible:
        return {
            "schema_version": 1,
            "status": STATUS_UNKNOWN,
            "reason": "no_completed_eligible_events_in_schedule",
            "as_of_date": as_of_date,
            "latest_completed_eligible_event": None,
            "latest_included_event": None,
            "missing_events": [],
            "missing_immediately_preceding": None,
            "excluded_events": excluded,
            **_manifest_info(frozen_manifest),
            "candidate_refresh": _candidate_refresh(canonical_dir),
        }
    eligible.sort(key=lambda event: (str(event["date_end"]), str(event["event_name"])))
    latest = eligible[-1]
    missing = []
    for event in eligible:
        source_id = _schedule_event_id(event.get("url"))
        season = str(event["date_start"])[:4]
        present = (source_id and source_id in canonical_ids) or (
            (_event_key(event["event_name"]), season) in canonical_names
        )
        if not present:
            missing.append(
                {
                    "event_name": event["event_name"],
                    "date_start": event["date_start"],
                    "date_end": event["date_end"],
                    "source_event_id": source_id,
                    "finality": "not_in_active_history",
                }
            )
    latest_present = (
        _schedule_event_id(latest.get("url")) in canonical_ids
        or (
            _event_key(latest["event_name"]),
            str(latest["date_start"])[:4],
        )
        in canonical_names
    )
    latest_included = (
        max(
            canonical_events,
            key=lambda row: (
                str(row.get("date_end") or ""),
                str(row.get("event_name") or ""),
            ),
        )
        if canonical_events
        else {}
    )
    return {
        "schema_version": 1,
        "status": STATUS_FRESH if not missing else STATUS_STALE,
        "reason": "" if not missing else "completed_events_missing_from_active_history",
        "as_of_date": as_of_date,
        "latest_completed_eligible_event": {
            "event_name": latest["event_name"],
            "date_start": latest["date_start"],
            "date_end": latest["date_end"],
            "source_event_id": _schedule_event_id(latest.get("url")),
            "present_in_active_history": latest_present,
        },
        "latest_included_event": {
            "event_name": latest_included.get("event_name", ""),
            "date_start": latest_included.get("date_start", ""),
            "date_end": latest_included.get("date_end", ""),
            "source_event_id": latest_included.get("source_event_id", ""),
        },
        "missing_events": missing,
        "missing_immediately_preceding": not latest_present,
        "eligible_event_count": len(eligible),
        "excluded_events": excluded,
        **_manifest_info(frozen_manifest),
        "candidate_refresh": _candidate_refresh(canonical_dir),
    }
