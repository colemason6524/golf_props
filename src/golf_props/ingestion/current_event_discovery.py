"""Discover the next main PGA Tour event from a preserved schedule source.

The schedule source (CBS Sports) is discovery/cross-check only. Its dates are
not authoritative for forecasting: competitive start dates and first-tee times
come from reviewed tee-time evidence later in the pipeline.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from golf_props.config import RAW_DIR
from golf_props.events.structure import scope_status
from golf_props.ingestion.cbs_results import (
    DEFAULT_SCHEDULE_URL,
    extract_schedule_events,
    fetch_page,
    event_slug,
)

RAW_SCHEDULE_DIR = RAW_DIR / "current_events" / "_schedule" / "latest"
SCHEDULE_SOURCE_ORG = "cbs_sports"


class CurrentEventDiscoveryError(ValueError):
    """Raised when the next event cannot be discovered."""


def utc_now() -> datetime:
    from golf_props.events.event_control import utc_now as _utc_now

    return _utc_now()


def discover_upcoming_events(
    schedule_html: str,
    as_of_date: date,
    source_url: str = DEFAULT_SCHEDULE_URL,
    source_org: str = SCHEDULE_SOURCE_ORG,
) -> dict[str, Any]:
    events = extract_schedule_events(schedule_html, as_of_date=as_of_date)
    upcoming = [
        {
            "event_name": event["event_name"],
            "season": date.fromisoformat(event["date_start"]).year,
            "date_start": event["date_start"],
            "date_end": event["date_end"],
            "course_name": event["course_name"],
            "location": event["location"],
            "source_event_id": event_slug(event),
            "url": event["url"],
        }
        for event in events
        if date.fromisoformat(event["date_start"]) >= as_of_date
    ]
    upcoming.sort(key=lambda event: (event["date_start"], event["event_name"]))
    return {
        "source": source_org,
        "source_url": source_url,
        "as_of_date": as_of_date.isoformat(),
        "upcoming_events": upcoming,
    }


def select_next_event(
    discovery: dict[str, Any],
    registry_rows: list[dict[str, str]],
) -> tuple[Optional[dict[str, Any]], list[str]]:
    upcoming = discovery["upcoming_events"]
    if not upcoming:
        return None, []
    blockers: list[str] = []
    first_start = upcoming[0]["date_start"]
    week_candidates = [
        event for event in upcoming if event["date_start"] == first_start
    ]
    included = []
    for event in week_candidates:
        status = scope_status(
            registry_rows,
            event["season"],
            event["event_name"],
            event["source_event_id"],
        )
        if status is True:
            included.append(event)
        elif status is False:
            blockers.append(f"excluded:{event['event_name']}")
        else:
            blockers.append(f"unreviewed:{event['event_name']}")
    if not included:
        return None, blockers
    if len(included) > 1:
        names = ", ".join(event["event_name"] for event in included)
        return None, [f"simultaneous_included_events:{names}"]
    return included[0], []


def fetch_and_preserve_schedule(
    raw_dir: Path = RAW_SCHEDULE_DIR,
    schedule_url: str = DEFAULT_SCHEDULE_URL,
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    captured_at = utc_now()
    raw_dir.mkdir(parents=True, exist_ok=True)
    status_code, html = fetch_page(schedule_url, timeout_seconds=timeout_seconds)
    if status_code != 200:
        raise CurrentEventDiscoveryError(
            f"schedule fetch failed with status {status_code}"
        )
    payload_path = raw_dir / "schedule.html"
    payload_path.write_text(html, encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "source_org": SCHEDULE_SOURCE_ORG,
        "url": schedule_url,
        "captured_at_utc": utc_now().isoformat().replace("+00:00", "Z"),
        "payload_path": str(payload_path),
        "payload_sha256": _sha256_text(html),
    }
    (raw_dir / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"manifest": manifest, "schedule_html": html}


def _sha256_text(content: str) -> str:
    import hashlib

    return hashlib.sha256(content.encode("utf-8")).hexdigest()
