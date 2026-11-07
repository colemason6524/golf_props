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

Outcome states
--------------
``in_progress``    the leaderboard is still live; quiet, retry next run
``pending``        ordinary wait: results not published yet, or finality not
                   provable.  No alert, retried on the existing timer.
``manual_review``  results are final but need a human decision (e.g. a tied or
                   unresolved winner); one private notice, never a fake grade
``failed``         a genuine transport/schema error; recorded plus one alert
``success``        a verified grade exists; a recap is then delivered from a
                   receipt keyed by the grade fingerprint

Every attempt also appends one line to ``grading_attempts.jsonl`` so a later
success can never erase the diagnosis of an earlier failure.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.error import HTTPError, URLError

from golf_props.backtest.forecast_grading import grade_forecast
from golf_props.config import PROJECT_ROOT
from golf_props.events.event_control import (
    STATE_FORECAST_ARCHIVED,
    EventControl,
    iso_timestamp,
    utc_now,
)
from golf_props.normalization.cbs_results import (
    FINALITY_FINAL,
    FINALITY_IN_PROGRESS,
    analyze_leaderboard_finality,
    parse_finish_position,
    parse_leaderboard_rows,
)

SCHEMA_VERSION = 1
GRADING_RECORD_NAME = "grading.json"
ATTEMPTS_RECORD_NAME = "grading_attempts.jsonl"

STATUS_IN_PROGRESS = "in_progress"
STATUS_PENDING = "pending"
STATUS_MANUAL_REVIEW = "manual_review"
STATUS_FAILED = "failed"
STATUS_SUCCESS = "success"

# Final leaderboards need a little time to settle after the final round before
# a grade is meaningful; one day of grace after ``schedule_end_date``.
RESULTS_GRACE_DAYS = 1

# Grading artifacts (graded_predictions.csv, metrics.csv, report.md, manifest).
GRADING_ROOT = PROJECT_ROOT / "data/interim/reports/forecast_grading"
# Public delivery artifacts (board + grade-recap receipts).
DELIVERY_ROOT = PROJECT_ROOT / "data/interim/reports/forecast_delivery"
# Preserved raw CBS leaderboard pages, one directory per event_key.
PROSPECTIVE_RESULTS_ROOT = PROJECT_ROOT / "data/raw/prospective_results"
# Immutable archived Bovada snapshots (additive capture, never latest-only).
ODDS_ARCHIVE_ROOT = PROJECT_ROOT / "data/raw/odds_snapshots/archive"
# Historical rolling expectation used as a reference column in the report.
# `rolling-simulation-validation` writes a fresh ``rolling_recompute_<YYYYMMDD>/``
# directory on every run, so the reference is resolved to the newest one rather
# than pinned to a literal path.  The previously pinned path
# (``rolling_round_simulation_validation/aggregate_metrics.csv``) has never
# existed in this repository; see docs/INTEGRITY_AUDIT_2026-10-22.md.
ROLLING_RECOMPUTE_GLOB = "rolling_recompute_*/aggregate_metrics.csv"

DEFAULT_DASHBOARD_PROJECT = "golf_props"
DASHBOARD_TIMEOUT_SECONDS = 60
RESULTS_TIMEOUT_SECONDS = 90

# Test seam: a callable ``(payload, url) -> outcome dict`` used to exercise
# recap delivery without any network.  Production leaves this ``None``.
RECAP_TRANSPORT_OVERRIDE: Optional[Callable[[dict, str], dict]] = None

_QUERY_STRING_RE = re.compile(r"\?[^\s'\"]+")


class PostEventGradingError(ValueError):
    """Raised when a grading attempt cannot proceed."""


class ResultsPendingError(PostEventGradingError):
    """Ordinary wait: the results are not published/provable yet."""

    def __init__(self, reason: str, *, stage: str, context: Optional[dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.stage = stage
        self.context = context or {}


class ResultsFetchError(PostEventGradingError):
    """Genuine transport/schema failure while collecting or parsing results."""

    def __init__(self, reason: str, *, stage: str, context: Optional[dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.stage = stage
        self.context = context or {}


class ManualReviewRequired(PostEventGradingError):
    """Final results that cannot be graded without a human decision."""

    def __init__(self, reason: str, *, stage: str, context: Optional[dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.stage = stage
        self.context = context or {}


class _TournamentInProgress(Exception):
    """Internal control-flow: the leaderboard is still live.

    Caught in :func:`attempt_post_event_grading` and turned into a quiet
    ``in_progress`` record -- no grading, no ops alert, no dashboard checkpoint.
    A mid-tournament loop run must say nothing alarming.
    """

    def __init__(self, reason: str, *, stage: str, context: Optional[dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.stage = stage
        self.context = context or {}


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

    Prefer an explicit override, then the newest recompute directory, so the
    loop keeps working across re-runs instead of depending on one dated path.
    """
    candidates: list[Path] = []
    override = os.environ.get("GOLF_PROPS_ROLLING_METRICS")
    if override:
        candidates.append(Path(override).expanduser())
    reports_root = PROJECT_ROOT / "data/interim/reports"
    if reports_root.exists():
        candidates.extend(
            sorted(reports_root.glob(ROLLING_RECOMPUTE_GLOB), reverse=True)
        )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _grading_record_path(paths: Any, event_key: str) -> Path:
    return paths.weekly_dir / event_key / GRADING_RECORD_NAME


def _attempts_record_path(paths: Any, event_key: str) -> Path:
    return paths.weekly_dir / event_key / ATTEMPTS_RECORD_NAME


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


def _sanitize_text(value: Any, limit: int = 400) -> str:
    """Strip secrets that could ride along in URLs, then bound the length."""
    text = _QUERY_STRING_RE.sub("?<redacted>", str(value))
    return text[:limit]


def _sanitize_context(context: Optional[dict[str, Any]]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in (context or {}).items():
        if isinstance(value, (int, float, bool)) or value is None:
            cleaned[str(key)] = value
        elif isinstance(value, dict):
            cleaned[str(key)] = _sanitize_context(value)
        elif isinstance(value, (list, tuple)):
            cleaned[str(key)] = [_sanitize_text(item, 200) for item in value][:20]
        else:
            cleaned[str(key)] = _sanitize_text(value)
    return cleaned


def _append_attempt(
    paths: Any,
    event_key: str,
    now: datetime,
    status: str,
    reason: str,
    stage: str,
    context: Optional[dict[str, Any]],
) -> None:
    """Append-only diagnosis trail; a later success never rewrites history."""
    entry = {
        "at_utc": iso_timestamp(now),
        "status": status,
        "reason": _sanitize_text(reason),
        "stage": stage,
        "context": _sanitize_context(context),
    }
    path = _attempts_record_path(paths, event_key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError:
        pass


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


def _classify_collection_error(exc: Exception) -> PostEventGradingError:
    """Separate an ordinary wait from a genuine collection failure."""
    if isinstance(exc, HTTPError):
        if int(exc.code) in {404, 410}:
            return ResultsPendingError(
                f"results page not published yet: HTTP {exc.code}",
                stage="collect_results",
                context={"http_status": int(exc.code)},
            )
        return ResultsFetchError(
            f"results fetch failed: HTTP {exc.code}",
            stage="collect_results",
            context={"http_status": int(exc.code)},
        )
    if isinstance(exc, (URLError, TimeoutError, OSError)):
        return ResultsFetchError(
            f"results fetch failed: {type(exc).__name__}",
            stage="collect_results",
            context={"error_type": type(exc).__name__},
        )
    return ResultsFetchError(
        f"results collection failed: {type(exc).__name__}",
        stage="collect_results",
        context={"error_type": type(exc).__name__},
    )


def _collect_event_results(
    event_key: str, event_name: str, now: datetime, timeout_seconds: int
) -> tuple[Path, str]:
    results_dir = PROSPECTIVE_RESULTS_ROOT / event_key
    preserved = _preserved_results_page(results_dir)
    if preserved is not None:
        return preserved
    from golf_props.ingestion.cbs_results import collect_cbs_results

    try:
        metadata = collect_cbs_results(
            results_dir, as_of_date=now.date(), timeout_seconds=timeout_seconds
        )
    except PostEventGradingError:
        raise
    except Exception as exc:
        raise _classify_collection_error(exc) from exc
    target = _name_key(event_name)
    events = list(metadata.get("events", []) or [])
    for event in events:
        if _name_key(str(event.get("event_name", ""))) != target:
            continue
        raw_path = Path(str(event.get("raw_path", "")))
        if raw_path.exists():
            return raw_path, str(event.get("url", ""))
    if not events:
        raise ResultsPendingError(
            f"CBS schedule lists no completed events yet for {event_name}",
            stage="match_schedule",
            context={"event_key": event_key, "schedule_event_count": 0},
        )
    raise ResultsPendingError(
        f"no completed CBS results row yet for {event_name} ({event_key})",
        stage="match_schedule",
        context={
            "event_key": event_key,
            "schedule_event_count": len(events),
            "schedule_events": [str(event.get("event_name", "")) for event in events][:20],
        },
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
    finality: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_key": event_key,
        "event_name": ec.event_name,
        "status": STATUS_SUCCESS,
        "recorded_at_utc": iso_timestamp(now),
        "output_dir": str(output_dir),
        "reused_existing_output": reused_existing,
        "results_page": str(results_page) if results_page else "",
        "results_url": results_url,
        "rolling_metrics": str(rolling) if rolling else "",
        "event_finality": finality or {"state": "final", "reason": "verified_grade"},
    }


def _winner_rows(page_html: str) -> list[str]:
    winners = []
    for row in parse_leaderboard_rows(page_html):
        if parse_finish_position(str(row["position"])) == 1:
            winners.append(str(row["player_name"]))
    return winners


def _grade_event(
    paths: Any,
    ec: EventControl,
    event_key: str,
    now: datetime,
    results_timeout_seconds: int,
) -> dict[str, Any]:
    archive_dir = paths.archive_dir(event_key)
    if not archive_dir.exists():
        raise ResultsFetchError(
            f"forecast archive missing: {archive_dir}",
            stage="locate_archive",
            context={"event_key": event_key},
        )
    output_dir = GRADING_ROOT / event_key
    if output_dir.exists() and any(output_dir.iterdir()):
        if not (output_dir / "grading_manifest.json").exists():
            raise ResultsFetchError(
                f"grading output directory is incomplete: {output_dir}",
                stage="adopt_existing_grade",
                context={"event_key": event_key},
            )
        # A complete grade already exists (e.g. produced manually before this
        # safeguard shipped); adopt it rather than re-grading.
        return _success_record(ec, event_key, now, output_dir, reused_existing=True)
    rolling = _rolling_metrics_path()
    if rolling is None:
        raise ResultsFetchError(
            "rolling metrics reference not found",
            stage="locate_rolling_metrics",
            context={"event_key": event_key},
        )
    results_page, results_url = _collect_event_results(
        event_key, ec.event_name, now, results_timeout_seconds
    )
    try:
        page_html = results_page.read_text(encoding="utf-8")
    except OSError as exc:
        raise ResultsFetchError(
            f"preserved results page unreadable: {type(exc).__name__}",
            stage="read_results_page",
            context={"event_key": event_key, "results_page": str(results_page)},
        ) from exc
    if not page_html:
        raise ResultsPendingError(
            f"preserved results page for {ec.event_name} is empty",
            stage="read_results_page",
            context={"event_key": event_key, "results_page": str(results_page)},
        )

    analysis = analyze_leaderboard_finality(page_html)
    finality = {"state": analysis["state"], "reason": analysis["reason"]}
    if analysis["state"] == FINALITY_IN_PROGRESS:
        raise _TournamentInProgress(
            f"leaderboard for {ec.event_name} ({event_key}) is still live",
            stage="finality",
            context={
                "event_key": event_key,
                "finality": finality,
                "finality_evidence": analysis["evidence"],
            },
        )
    if analysis["state"] != FINALITY_FINAL:
        raise ResultsPendingError(
            f"finality not provable for {ec.event_name}: {analysis['reason']}",
            stage="finality",
            context={
                "event_key": event_key,
                "finality": finality,
                "finality_evidence": analysis["evidence"],
            },
        )

    # A tie for first (or an unresolved playoff row) is a real-world result the
    # grader refuses to collapse into one winner; never fabricate a grade.
    winners = _winner_rows(page_html)
    if len(winners) != 1:
        raise ManualReviewRequired(
            f"winner unresolved for {ec.event_name}: {len(winners)} player(s) at position 1",
            stage="winner_check",
            context={
                "event_key": event_key,
                "winner_rows": winners[:10],
                "winner_row_count": len(winners),
                "finality": finality,
            },
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
        finality=finality,
    )


def _record_status(
    paths: Any,
    ec: EventControl,
    event_key: str,
    now: datetime,
    status: str,
    reason: str,
    stage: str,
    context: Optional[dict[str, Any]],
    previous: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Persist a non-success attempt and append it to the attempt log."""
    alerted = not (
        previous
        and previous.get("status") == status
        and previous.get("reason") == reason
    )
    record = {
        "schema_version": SCHEMA_VERSION,
        "event_key": event_key,
        "event_name": ec.event_name,
        "status": status,
        "recorded_at_utc": iso_timestamp(now),
        "reason": _sanitize_text(reason),
        "stage": stage,
        "context": _sanitize_context(context),
        "output_dir": str(GRADING_ROOT / event_key),
        "alerted": alerted,
    }
    _write_record(_grading_record_path(paths, event_key), record)
    _append_attempt(paths, event_key, now, status, reason, stage, context)
    return record


def _record_failure(
    paths: Any,
    ec: EventControl,
    event_key: str,
    now: datetime,
    reason: str,
    previous: Optional[dict[str, Any]],
    stage: str = "unknown",
    context: Optional[dict[str, Any]] = None,
) -> None:
    record = _record_status(
        paths, ec, event_key, now, STATUS_FAILED, reason, stage, context, previous
    )
    if not record["alerted"]:
        # Same failure as the previous attempt: retry quietly instead of
        # re-firing the urgent alert every two hours.
        return
    # Discord gets a clean, human line -- never the raw exception text.
    # The full ``reason`` stays in grading.json, grading_attempts.jsonl and logs.
    message = (
        f"golf post-event grading for {ec.event_name} could not finish yet; "
        "will retry next run"
    )
    _notify_ops(message)
    _dashboard_checkpoint("blocked", f"[URGENT] {message}")


def _review_notice(ec: EventControl, record: dict[str, Any]) -> None:
    """One private operator notice when final results need a human decision."""
    if not record.get("alerted"):
        return
    count = (record.get("context") or {}).get("winner_row_count")
    detail = f" ({count} players at position 1)" if count else ""
    message = (
        f"golf post-event grading for {ec.event_name} needs manual review"
        f"{detail}; no grade was written"
    )
    _notify_ops(message)
    _dashboard_checkpoint("blocked", message)


def _event_dates(ec: EventControl) -> dict[str, str]:
    start = ec.competitive_start_date or ec.schedule_start_date or ""
    if ec.competitive_start_date:
        source = "event_control.competitive_start_date"
    elif ec.schedule_start_date:
        source = "event_control.schedule_start_date"
    else:
        source = "not recorded"
    return {"start": start, "end": ec.schedule_end_date or "", "source": source}


def _deliver_recap(
    paths: Any,
    ec: EventControl,
    event_key: str,
    record: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Build/deliver the final recap for one verified grade; never surprises."""
    from golf_props.notifications.grade_recap import ensure_grade_recap

    grading_dir = GRADING_ROOT / event_key
    delivery_dir = DELIVERY_ROOT / event_key
    results_page = Path(record["results_page"]) if record.get("results_page") else None
    finality = record.get("event_finality") or {
        "state": "final",
        "reason": "verified_grade",
    }
    return ensure_grade_recap(
        event_key=event_key,
        event_name=ec.event_name,
        delivery_dir=delivery_dir,
        grading_dir=grading_dir,
        results_page=results_page,
        event_dates=_event_dates(ec),
        finality=finality,
        odds_archive_dir=ODDS_ARCHIVE_ROOT,
        transport=RECAP_TRANSPORT_OVERRIDE,
        now=now,
        weekly_dir=paths.weekly_dir,
    )


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

    Idempotent and fail-safe: a ``success`` side record short-circuits re-grading
    (but not recap delivery, which has its own receipt), and any error is
    recorded and classified instead of raised.  The loop stays fast because only
    local ``event_control.json``/``grading.json`` checks run until an event is
    genuinely eligible for grading.
    """
    now = now or utc_now()
    summary: dict[str, Any] = {
        "checked_at_utc": iso_timestamp(now),
        "graded": [],
        "failed": [],
        "pending": [],
        "in_progress": [],
        "manual_review": [],
        "skipped": [],
        "recap": [],
    }
    successful: list[tuple[EventControl, str, dict[str, Any]]] = []
    for ec, event_key in _archived_events(paths):
        record_path = _grading_record_path(paths, event_key)
        previous = _read_record(record_path)
        if previous and previous.get("status") == STATUS_SUCCESS:
            summary["skipped"].append(
                {"event_key": event_key, "reason": "already_graded"}
            )
            # Keep an undelivered recap reachable: a previous pending/error
            # notice must not suppress the final message forever.
            successful.append((ec, event_key, previous))
            continue
        if not _results_ready(ec, now):
            summary["skipped"].append(
                {"event_key": event_key, "reason": "tournament_not_finished"}
            )
            continue
        try:
            record = _grade_event(paths, ec, event_key, now, results_timeout_seconds)
        except _TournamentInProgress as exc:
            _record_status(
                paths, ec, event_key, now, STATUS_IN_PROGRESS, exc.reason,
                exc.stage, exc.context, previous,
            )
            summary["in_progress"].append(
                {"event_key": event_key, "reason": exc.reason}
            )
            continue
        except ResultsPendingError as exc:
            _record_status(
                paths, ec, event_key, now, STATUS_PENDING, exc.reason,
                exc.stage, exc.context, previous,
            )
            summary["pending"].append({"event_key": event_key, "reason": exc.reason})
            continue
        except ManualReviewRequired as exc:
            record = _record_status(
                paths, ec, event_key, now, STATUS_MANUAL_REVIEW, exc.reason,
                exc.stage, exc.context, previous,
            )
            _review_notice(ec, record)
            summary["manual_review"].append(
                {"event_key": event_key, "reason": exc.reason}
            )
            continue
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            _record_failure(
                paths, ec, event_key, now, reason, previous,
                stage=getattr(exc, "stage", "grading"),
                context=getattr(exc, "context", None),
            )
            summary["failed"].append({"event_key": event_key, "reason": reason})
            continue
        _write_record(record_path, record)
        _append_attempt(
            paths, event_key, now, STATUS_SUCCESS, "verified grade", "grade",
            {
                "output_dir": record["output_dir"],
                "event_finality": record.get("event_finality"),
            },
        )
        _dashboard_checkpoint(
            "observing", f"golf_props graded {ec.event_name} ({event_key})"
        )
        summary["graded"].append(
            {"event_key": event_key, "output_dir": record["output_dir"]}
        )
        successful.append((ec, event_key, record))

    # Recap delivery is independent of grading idempotency: every verified grade
    # gets one receipt-checked attempt, including grades produced in earlier runs.
    for ec, event_key, record in successful:
        try:
            result = _deliver_recap(paths, ec, event_key, record, now)
        except Exception as exc:  # a recap must never break the forecast loop
            summary["recap"].append(
                {
                    "event_key": event_key,
                    "status": "error",
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        summary["recap"].append(
            {
                "event_key": event_key,
                "status": result.get("status", ""),
                "grade_fingerprint": result.get("recap", {}).get("fingerprint", ""),
            }
        )
    return summary
