"""Automatic post-event grading attempt for the weekly forecast loop.

The weekly loop archives exactly one immutable forecast per event.  Grading
that archive against the final leaderboard used to be a manual step and was
silently missed for the Bank of Utah Championship, so the loop now attempts it
automatically once the tournament has ended (plus one day of grace for the
final leaderboard to settle).

Grading never touches the event state machine: ``forecast_archived`` is
terminal with no outgoing transitions.  The outcome is written to a side record,
``data/interim/weekly/<event_key>/grading.json``, which doubles as the
idempotency key -- a ``success`` record short-circuits every later run.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from golf_props.backtest.forecast_grading import grade_forecast
from golf_props.config import PROJECT_ROOT
from golf_props.events.event_control import (
    STATE_FORECAST_ARCHIVED,
    EventControl,
    iso_timestamp,
    utc_now,
)

SCHEMA_VERSION = 1
GRADING_RECORD_NAME = "grading.json"

# Final leaderboards need a little time to settle after the final round before
# a grade is meaningful; one day of grace after ``schedule_end_date``.
RESULTS_GRACE_DAYS = 1

# Grading artifacts (graded_predictions.csv, metrics.csv, report.md, manifest).
GRADING_ROOT = PROJECT_ROOT / "data/interim/reports/forecast_grading"
# Preserved raw CBS leaderboard pages, one directory per event_key.
PROSPECTIVE_RESULTS_ROOT = PROJECT_ROOT / "data/raw/prospective_results"
# Historical rolling expectation used as a reference column in the report.
DEFAULT_ROLLING_METRICS = (
    PROJECT_ROOT
    / "data/interim/reports/rolling_round_simulation_validation/aggregate_metrics.csv"
)

DEFAULT_DASHBOARD_PROJECT = "golf_props"
DASHBOARD_TIMEOUT_SECONDS = 60
RESULTS_TIMEOUT_SECONDS = 90


class PostEventGradingError(ValueError):
    """Raised when a grading attempt cannot proceed."""


def _notify_ops(message: str) -> None:
    """Send an urgent operational alert; never raises.

    ``send_ops_alert`` adds the ``[URGENT]`` prefix itself, so callers pass a
    plain message here.
    """
    try:
        from golf_props.notifications.discord import send_ops_alert

        send_ops_alert(message)
    except Exception:
        pass


def _dashboard_checkpoint(
    status: str, summary: str, project: str = DEFAULT_DASHBOARD_PROJECT
) -> bool:
    """Post one dashboard journal entry; never raises, never blocks the loop."""
    dashboard_dir = Path(
        os.environ.get("GOLF_PROPS_DASHBOARD_DIR") or (Path.home() / "dashboard")
    )
    if not dashboard_dir.exists():
        return False
    try:
        completed = subprocess.run(
            [
                "python3",
                "-m",
                "dashboard",
                "checkpoint-update",
                "--project",
                project,
                "--status",
                status,
                # grade_event kind needs no numeric --target (the default
                # game_days kind would be rejected without one).
                "--kind",
                "grade_event",
                "--label",
                "post-event forecast grading",
                "--summary",
                summary,
            ],
            cwd=str(dashboard_dir),
            capture_output=True,
            text=True,
            timeout=DASHBOARD_TIMEOUT_SECONDS,
        )
        return completed.returncode == 0
    except Exception:
        return False


def _rolling_metrics_path() -> Optional[Path]:
    """Resolve the rolling-metrics reference the grader needs.

    The Bank of Utah manual grade used the recompute output; prefer an explicit
    override, then the documented validation path, then the newest recompute
    directory so the loop keeps working after a re-run.
    """
    candidates: list[Path] = []
    override = os.environ.get("GOLF_PROPS_ROLLING_METRICS")
    if override:
        candidates.append(Path(override).expanduser())
    candidates.append(DEFAULT_ROLLING_METRICS)
    reports_root = PROJECT_ROOT / "data/interim/reports"
    if reports_root.exists():
        candidates.extend(
            sorted(
                reports_root.glob("rolling_recompute_*/aggregate_metrics.csv"),
                reverse=True,
            )
        )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _grading_record_path(paths: Any, event_key: str) -> Path:
    return paths.weekly_dir / event_key / GRADING_RECORD_NAME


def _read_record(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def _write_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _schedule_end(ec: EventControl) -> Optional[date]:
    if not ec.schedule_end_date:
        return None
    try:
        return date.fromisoformat(ec.schedule_end_date)
    except ValueError:
        return None


def _results_ready(ec: EventControl, now: datetime) -> bool:
    ends = _schedule_end(ec)
    if ends is None:
        return False
    return now.date() >= ends + timedelta(days=RESULTS_GRACE_DAYS)


def _name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def _preserved_results_page(results_dir: Path) -> Optional[tuple[Path, str]]:
    """Reuse a leaderboard page already preserved for this event.

    The manual Bank of Utah grade left ``source_manifest.json`` plus a CBS
    leaderboard page; reuse it so the safeguard is network-free and repeatable.
    """
    manifest = results_dir / "source_manifest.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        if isinstance(data, dict):
            url = str(data.get("leaderboard_url") or "")
            for name in data.get("files", {}) or {}:
                candidate = results_dir / str(name)
                if candidate.exists() and "leaderboard" in str(name).casefold():
                    return candidate, url
    if results_dir.exists():
        for candidate in sorted(results_dir.glob("*.html")):
            if "leaderboard" in candidate.name.casefold():
                return candidate, ""
    return None


def _collect_event_results(
    event_key: str, event_name: str, now: datetime, timeout_seconds: int
) -> tuple[Path, str]:
    results_dir = PROSPECTIVE_RESULTS_ROOT / event_key
    preserved = _preserved_results_page(results_dir)
    if preserved is not None:
        return preserved
    from golf_props.ingestion.cbs_results import collect_cbs_results

    metadata = collect_cbs_results(
        results_dir, as_of_date=now.date(), timeout_seconds=timeout_seconds
    )
    target = _name_key(event_name)
    for event in metadata.get("events", []) or []:
        if _name_key(str(event.get("event_name", ""))) != target:
            continue
        raw_path = Path(str(event.get("raw_path", "")))
        if raw_path.exists():
            return raw_path, str(event.get("url", ""))
    raise PostEventGradingError(
        f"no preserved CBS results for {event_name} ({event_key})"
    )


def _success_record(
    ec: EventControl,
    event_key: str,
    now: datetime,
    output_dir: Path,
    reused_existing: bool,
    results_page: Optional[Path] = None,
    results_url: str = "",
    rolling: Optional[Path] = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_key": event_key,
        "event_name": ec.event_name,
        "status": "success",
        "recorded_at_utc": iso_timestamp(now),
        "output_dir": str(output_dir),
        "reused_existing_output": reused_existing,
        "results_page": str(results_page) if results_page else "",
        "results_url": results_url,
        "rolling_metrics": str(rolling) if rolling else "",
    }


def _grade_event(
    paths: Any,
    ec: EventControl,
    event_key: str,
    now: datetime,
    results_timeout_seconds: int,
) -> dict[str, Any]:
    archive_dir = paths.archive_dir(event_key)
    if not archive_dir.exists():
        raise PostEventGradingError(f"forecast archive missing: {archive_dir}")
    output_dir = GRADING_ROOT / event_key
    if output_dir.exists() and any(output_dir.iterdir()):
        if not (output_dir / "grading_manifest.json").exists():
            raise PostEventGradingError(
                f"grading output directory is incomplete: {output_dir}"
            )
        # A complete grade already exists (e.g. produced manually before this
        # safeguard shipped); adopt it rather than re-grading.
        return _success_record(ec, event_key, now, output_dir, reused_existing=True)
    rolling = _rolling_metrics_path()
    if rolling is None:
        raise PostEventGradingError("rolling metrics reference not found")
    results_page, results_url = _collect_event_results(
        event_key, ec.event_name, now, results_timeout_seconds
    )
    grade_forecast(
        archive_dir,
        results_page,
        rolling,
        output_dir,
        results_url=results_url,
        created_at=now,
    )
    return _success_record(
        ec,
        event_key,
        now,
        output_dir,
        reused_existing=False,
        results_page=results_page,
        results_url=results_url,
        rolling=rolling,
    )


def _record_failure(
    paths: Any,
    ec: EventControl,
    event_key: str,
    now: datetime,
    reason: str,
    previous: Optional[dict[str, Any]],
) -> None:
    alerted = not (
        previous
        and previous.get("status") == "failed"
        and previous.get("reason") == reason
    )
    record = {
        "schema_version": SCHEMA_VERSION,
        "event_key": event_key,
        "event_name": ec.event_name,
        "status": "failed",
        "recorded_at_utc": iso_timestamp(now),
        "reason": reason,
        "output_dir": str(GRADING_ROOT / event_key),
        "alerted": alerted,
    }
    _write_record(_grading_record_path(paths, event_key), record)
    if not alerted:
        # Same failure as the previous attempt: retry quietly instead of
        # re-firing the urgent alert every two hours.
        return
    # Discord gets a clean, human line -- never the raw exception text.
    # The full ``reason`` stays in grading.json, status.json, and the logs.
    message = (
        f"golf post-event grading for {ec.event_name} could not finish yet; "
        "will retry next run"
    )
    _notify_ops(message)
    _dashboard_checkpoint("blocked", f"[URGENT] {message}")


def _archived_events(paths: Any) -> list[tuple[EventControl, str]]:
    events: list[tuple[EventControl, str]] = []
    if not paths.weekly_dir.exists():
        return events
    for control_path in sorted(paths.weekly_dir.glob("*/event_control.json")):
        ec = EventControl.load(control_path)
        if ec is None or ec.state != STATE_FORECAST_ARCHIVED:
            continue
        events.append((ec, ec.event_key or control_path.parent.name))
    return events


def attempt_post_event_grading(
    paths: Any,
    now: Optional[datetime] = None,
    results_timeout_seconds: int = RESULTS_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Attempt to grade every ended, ungraded archived forecast.

    Idempotent and fail-safe: a ``success`` side record short-circuits later
    runs, and any error is recorded plus alerted instead of raised.  The loop
    stays fast because only local ``event_control.json``/``grading.json``
    checks run until an event is genuinely eligible for grading.
    """
    now = now or utc_now()
    summary: dict[str, Any] = {
        "checked_at_utc": iso_timestamp(now),
        "graded": [],
        "failed": [],
        "skipped": [],
    }
    for ec, event_key in _archived_events(paths):
        record_path = _grading_record_path(paths, event_key)
        previous = _read_record(record_path)
        if previous and previous.get("status") == "success":
            summary["skipped"].append(
                {"event_key": event_key, "reason": "already_graded"}
            )
            continue
        if not _results_ready(ec, now):
            summary["skipped"].append(
                {"event_key": event_key, "reason": "tournament_not_finished"}
            )
            continue
        try:
            record = _grade_event(paths, ec, event_key, now, results_timeout_seconds)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            _record_failure(paths, ec, event_key, now, reason, previous)
            summary["failed"].append({"event_key": event_key, "reason": reason})
            continue
        _write_record(record_path, record)
        _dashboard_checkpoint(
            "observing", f"golf_props graded {ec.event_name} ({event_key})"
        )
        summary["graded"].append(
            {"event_key": event_key, "output_dir": record["output_dir"]}
        )
    return summary
