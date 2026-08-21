"""Weekly frozen forecast orchestrator: idempotent and fail-closed.

The orchestrator discovers the next main PGA Tour event, waits for reviewed
field and tee-time evidence, resolves player identities, and produces exactly
one immutable primary forecast archive before the verified first tee. It never
overwrites an archived forecast and never guesses about event timing or
structure.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from golf_props.config import PROCESSED_DIR, PROJECT_ROOT, RAW_DIR
from golf_props.events.event_control import (
    STATE_AWAITING_FIELD,
    STATE_AWAITING_IDENTITY,
    STATE_AWAITING_TEE_TIMES,
    STATE_BLOCKED,
    STATE_DEADLINE_MISSED,
    STATE_DISCOVERED,
    STATE_FORECAST_ARCHIVED,
    STATE_FORECAST_READY,
    TERMINAL_STATES,
    EventControl,
    iso_timestamp,
    utc_now,
)
from golf_props.events.structure import (
    DEFAULT_REGISTRY_PATH,
    read_registry,
    resolve_structure,
)
from golf_props.ingestion.current_event_discovery import (
    DEFAULT_SCHEDULE_URL,
    CurrentEventDiscoveryError,
    discover_upcoming_events,
    fetch_and_preserve_schedule,
    select_next_event,
)
from golf_props.ingestion.current_field import (
    FIELD_REQUIRED_COLUMNS,
    FIELDS_ROOT,
    bovada_field_cross_check,
    load_latest_field_evidence,
    write_field_csv,
)
from golf_props.ingestion.tee_times import (
    TEE_TIMES_ROOT,
    load_latest_tee_time_evidence,
    write_tee_times_csv,
)
from golf_props.normalization.player_identity import (
    write_identity_audit,
    write_resolved_field_csv,
    resolve_field_identities,
)
from golf_props.pipelines.current_event_simulation import (
    FrozenCurrentEventError,
    run_frozen_current_event,
)

EXIT_WAITING = 0
EXIT_BLOCKED = 10
EXIT_DEADLINE_MISSED = 11
EXIT_IDENTITY_BLOCKED = 12
EXIT_ERROR = 20

FORECAST_DUE_HOURS_BEFORE = 12

DEFAULT_BOVADA_SNAPSHOT = (
    PROJECT_ROOT / "data" / "processed" / "odds_snapshots" / "bovada_golf_latest.csv"
)


class WeeklyForecastError(ValueError):
    """Raised when the weekly forecast cannot proceed safely."""


class NoNextEventError(WeeklyForecastError):
    """Raised when the schedule has no upcoming events at all."""


@dataclass
class WeeklyPaths:
    manifest: Path = (
        PROJECT_ROOT
        / "data/interim/reports/rolling_round_simulation_validation/frozen_model_manifest.json"
    )
    round_performance: Path = (
        PROJECT_ROOT
        / "data/interim/features/pga_2001_2026_round_performance.csv"
    )
    canonical_dir: Path = PROJECT_ROOT / "data/processed/pga_2001_2026"
    aliases: Path = PROJECT_ROOT / "config/player_aliases.csv"
    registry: Path = DEFAULT_REGISTRY_PATH
    weekly_dir: Path = PROJECT_ROOT / "data/interim/weekly"
    raw_events_root: Path = FIELDS_ROOT
    processed_events_root: Path = PROCESSED_DIR / "current_events"
    archives_root: Path = (
        PROJECT_ROOT / "data/interim/reports/prospective_forecasts"
    )
    raw_schedule_dir: Path = RAW_DIR / "current_events" / "_schedule" / "latest"
    bovada_snapshot: Path = DEFAULT_BOVADA_SNAPSHOT

    @property
    def status_path(self) -> Path:
        return self.weekly_dir / "status.json"

    @property
    def pointer_path(self) -> Path:
        return self.weekly_dir / "current_event_key.txt"

    def event_control_path(self, event_key: str) -> Path:
        return self.weekly_dir / event_key / "event_control.json"

    def identity_audit_path(self, event_key: str) -> Path:
        return self.weekly_dir / event_key / "identity_audit.json"

    def field_raw_path(self, event_key: str) -> Path:
        return self.processed_events_root / event_key / "field_raw.csv"

    def field_path(self, event_key: str) -> Path:
        return self.processed_events_root / event_key / "field.csv"

    def tee_times_path(self, event_key: str) -> Path:
        return self.processed_events_root / event_key / "tee_times.csv"

    def archive_dir(self, event_key: str) -> Path:
        return self.archives_root / event_key


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _base_status(
    now: datetime,
    forecast_due_hours_before: int,
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "state": "",
        "event_key": "",
        "event_name": "",
        "season": 0,
        "competitive_start_date": "",
        "first_tee_at_utc": None,
        "forecast_due_at_utc": None,
        "forecast_due_hours_before": forecast_due_hours_before,
        "expected_field_size": None,
        "field_ready": False,
        "field_source_kind": None,
        "field_finality": None,
        "field_cross_check_size": None,
        "tee_times_ready": False,
        "identity_matched": 0,
        "identity_problems": [],
        "structure": None,
        "blocking_reason": "",
        "last_attempt_at_utc": iso_timestamp(now),
        "last_error": "",
        "archive_path": None,
        "time_remaining_seconds": None,
        "dry_run": dry_run,
    }


def _load_players(paths: WeeklyPaths) -> list[dict[str, str]]:
    import csv

    players_path = paths.canonical_dir / "players.csv"
    if not players_path.exists():
        raise WeeklyForecastError(f"missing canonical players table: {players_path}")
    with players_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _load_or_discover(
    paths: WeeklyPaths,
    now: datetime,
    schedule_html: Optional[str],
    schedule_url: str,
) -> tuple[Optional[EventControl], str]:
    if paths.pointer_path.exists():
        key = paths.pointer_path.read_text(encoding="utf-8").strip()
        ec = EventControl.load(paths.event_control_path(key))
        if ec is not None and ec.state not in TERMINAL_STATES:
            if ec.structure_decision is None:
                structure = resolve_structure(
                    read_registry(paths.registry),
                    ec.season,
                    ec.event_name,
                    ec.source_event_id,
                )
                if structure is None:
                    raise WeeklyForecastError(
                        f"no reviewed event-structure decision for {ec.event_name}"
                    )
                ec.structure_decision = structure
                ec.save(paths.event_control_path(key))
            return ec, key

    html = schedule_html
    if html is None:
        try:
            fetch_and_preserve_schedule(
                raw_dir=paths.raw_schedule_dir,
                schedule_url=schedule_url,
            )
        except Exception as exc:
            raise CurrentEventDiscoveryError(
                f"schedule fetch failed: {exc}"
            ) from exc
        html = (paths.raw_schedule_dir / "schedule.html").read_text(
            encoding="utf-8"
        )
    discovery = discover_upcoming_events(
        html,
        as_of_date=now.date(),
        source_url=schedule_url,
    )
    registry = read_registry(paths.registry)
    selected, blockers = select_next_event(discovery, registry)
    if selected is None:
        if not blockers:
            raise NoNextEventError("no upcoming events")
        raise WeeklyForecastError(
            "no next event selected: " + "; ".join(blockers)
        )
    key = f"{_event_key(selected['event_name'], selected['season'])}"
    existing = EventControl.load(paths.event_control_path(key))
    if existing is not None and existing.state in TERMINAL_STATES:
        return existing, key
    structure = resolve_structure(
        registry,
        int(selected["season"]),
        selected["event_name"],
        selected["source_event_id"],
    )
    if structure is None:
        raise WeeklyForecastError(
            f"no reviewed event-structure decision for {selected['event_name']}"
        )
    ec = _new_control(selected, now)
    ec.structure_decision = structure
    ec.save(paths.event_control_path(key))
    paths.pointer_path.write_text(key, encoding="utf-8")
    return ec, key


def _event_key(event_name: str, season: int) -> str:
    from golf_props.features.current_event import normalize_name

    slug = " ".join(normalize_name(event_name).split("_"))
    slug = "_".join(slug.split())
    return f"{slug}_{season}"


def _new_control(selected: dict[str, Any], now: datetime) -> EventControl:
    return EventControl(
        event_key="",
        event_name=selected["event_name"],
        season=int(selected["season"]),
        source_event_id=selected["source_event_id"],
        schedule_start_date=selected["date_start"],
        schedule_end_date=selected["date_end"],
        course_name=selected["course_name"],
        course_location=selected["location"],
        state=STATE_DISCOVERED,
        created_at_utc=iso_timestamp(now),
        updated_at_utc=iso_timestamp(now),
    )


def _set_key(ec: EventControl, key: str) -> None:
    ec.event_key = key


def _try_field(
    paths: WeeklyPaths,
    ec: EventControl,
    now: datetime,
) -> dict[str, Any]:
    evidence = load_latest_field_evidence(ec.event_key, raw_root=paths.raw_events_root)
    if evidence is not None and evidence.ready():
        rows = [
            {
                "player_name": row["player_name"],
                "player_id": row["player_id"],
                "entry_status": row["entry_status"],
            }
            for row in evidence.rows
        ]
        write_field_csv(paths.field_raw_path(ec.event_key), rows)
        ec.field_source = evidence.to_dict()
        ec.expected_field_size = evidence.expected_field_size
        ec.transition(
            STATE_AWAITING_TEE_TIMES,
            "official final field evidence preserved",
            now,
        )
        return {"ready": True}
    cross = bovada_field_cross_check(paths.bovada_snapshot)
    if ec.state == STATE_DISCOVERED:
        ec.transition(STATE_AWAITING_FIELD, "awaiting official final field evidence", now)
    return {
        "ready": False,
        "reason": "awaiting official final field evidence",
        "cross_check_size": cross.get("field_size"),
    }


def _apply_tee_times(
    paths: WeeklyPaths,
    ec: EventControl,
    now: datetime,
    forecast_due_hours_before: int,
) -> bool:
    evidence = load_latest_tee_time_evidence(ec.event_key, raw_root=paths.raw_events_root)
    if evidence is None or not evidence.earliest_tee_at_utc:
        return False
    first_tee = parse_iso(evidence.earliest_tee_at_utc)
    if ec.first_tee_at_utc != evidence.earliest_tee_at_utc:
        ec.first_tee_at_utc = evidence.earliest_tee_at_utc
        ec.competitive_start_date = first_tee.date().isoformat()
        ec.forecast_due_at_utc = iso_timestamp(
            first_tee - timedelta(hours=forecast_due_hours_before)
        )
        ec.tee_time_source = evidence.to_dict()
        write_tee_times_csv(
            paths.tee_times_path(ec.event_key),
            evidence.rows,
            evidence.earliest_tee_at_utc,
        )
        if ec.state == STATE_AWAITING_TEE_TIMES:
            ec.transition(
                STATE_AWAITING_IDENTITY,
                "first tee verified from reviewed evidence",
                now,
            )
        ec.save(paths.event_control_path(ec.event_key))
    return True


def _apply_identity(
    paths: WeeklyPaths,
    ec: EventControl,
    now: datetime,
    players_rows: list[dict[str, str]],
) -> bool:
    field_path = paths.field_raw_path(ec.event_key)
    import csv

    with field_path.open(newline="", encoding="utf-8") as handle:
        field_rows = list(csv.DictReader(handle))
    prior_ids = {
        row["player_id"]
        for row in field_rows
        if str(row.get("player_id") or "").strip()
    }
    resolved, audit = resolve_field_identities(
        field_rows,
        players_rows,
        aliases_path=paths.aliases,
        prior_player_ids=prior_ids,
    )
    write_identity_audit(paths.identity_audit_path(ec.event_key), audit)
    write_resolved_field_csv(paths.field_path(ec.event_key), resolved)
    if not audit["ok"]:
        ec.transition(STATE_BLOCKED, "unresolved field identities", now)
        ec.save(paths.event_control_path(ec.event_key))
        return False
    if ec.state == STATE_AWAITING_IDENTITY:
        ec.transition(STATE_FORECAST_READY, "all field identities resolved", now)
        ec.save(paths.event_control_path(ec.event_key))
    return True


def _copy_evidence_to_staging(
    staging: Path,
    paths: WeeklyPaths,
    ec: EventControl,
    identity_audit: dict[str, Any],
) -> None:
    import json

    shutil.copyfile(paths.field_path(ec.event_key), staging / "field.csv")
    shutil.copyfile(paths.field_raw_path(ec.event_key), staging / "field_raw.csv")
    shutil.copyfile(
        paths.tee_times_path(ec.event_key),
        staging / "tee_times.csv",
    )
    (staging / "event.json").write_text(
        json.dumps(ec.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (staging / "field_source_manifest.json").write_text(
        json.dumps(ec.field_source, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (staging / "tee_time_source_manifest.json").write_text(
        json.dumps(ec.tee_time_source, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (staging / "structure_decision.json").write_text(
        json.dumps(ec.structure_decision, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (staging / "identity_audit.json").write_text(
        json.dumps(identity_audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_archive_manifest(archive_dir: Path) -> dict[str, str]:
    from golf_props.ingestion.current_field import sha256_file

    files = sorted(
        path.name
        for path in archive_dir.iterdir()
        if path.is_file() and path.name != "archive_manifest.json"
    )
    hashes = {name: sha256_file(archive_dir / name) for name in files}
    manifest = {
        "schema_version": 1,
        "files": hashes,
    }
    (archive_dir / "archive_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _run_forecast(
    paths: WeeklyPaths,
    ec: EventControl,
    now: datetime,
    simulations: int,
    top_n: int,
) -> dict[str, Any]:
    archive_dir = paths.archive_dir(ec.event_key)
    if (archive_dir / "run_manifest.json").exists():
        ec.transition(STATE_FORECAST_ARCHIVED, "forecast already archived", now)
        ec.save(paths.event_control_path(ec.event_key))
        return {"archived": True}
    structure = ec.structure_decision or {}
    cut_rule = str(structure.get("cut_rule") or "top_n_and_ties")
    staging = (
        paths.weekly_dir / ec.event_key / f"staging_{now.strftime('%Y%m%dT%H%M%SZ')}"
    )
    staging.mkdir(parents=True, exist_ok=True)
    try:
        run_frozen_current_event(
            paths.manifest,
            paths.field_path(ec.event_key),
            staging,
            ec.event_name,
            ec.competitive_start_date,
            simulations=simulations,
            top_n=top_n,
            cut_rule=cut_rule,
            event_start_at_utc=ec.first_tee_at_utc,
        )
    except FrozenCurrentEventError as exc:
        ec.transition(STATE_BLOCKED, f"frozen forecast refused: {exc}", now)
        ec.save(paths.event_control_path(ec.event_key))
        shutil.rmtree(staging, ignore_errors=True)
        return {"archived": False, "blocked": str(exc)}
    audit_path = paths.identity_audit_path(ec.event_key)
    identity_audit = json.loads(audit_path.read_text(encoding="utf-8"))
    _copy_evidence_to_staging(staging, paths, ec, identity_audit)
    _write_archive_manifest(staging)
    if archive_dir.exists():
        raise WeeklyForecastError(
            f"archive directory already exists: {archive_dir}"
        )
    archive_dir.parent.mkdir(parents=True, exist_ok=True)
    os.replace(str(staging), str(archive_dir))
    ec.transition(STATE_FORECAST_ARCHIVED, "primary forecast archived", now)
    ec.save(paths.event_control_path(ec.event_key))
    return {"archived": True, "archive_dir": str(archive_dir)}


def _finalize(
    paths: WeeklyPaths,
    status: dict[str, Any],
    ec: Optional[EventControl],
) -> None:
    if ec is not None:
        status["state"] = ec.state
        status["event_key"] = ec.event_key
        status["event_name"] = ec.event_name
        status["season"] = ec.season
        status["competitive_start_date"] = ec.competitive_start_date
        status["first_tee_at_utc"] = ec.first_tee_at_utc
        status["forecast_due_at_utc"] = ec.forecast_due_at_utc
        status["expected_field_size"] = ec.expected_field_size
        status["structure"] = ec.structure_decision
        status["blocking_reason"] = ec.blocking_reason
        if ec.field_source:
            status["field_source_kind"] = ec.field_source.get("source_kind")
            status["field_finality"] = ec.field_source.get("finality")
            status["field_ready"] = True
        if ec.first_tee_at_utc:
            status["tee_times_ready"] = True
        if ec.state == STATE_FORECAST_ARCHIVED:
            status["archive_path"] = str(paths.archive_dir(ec.event_key))
    now = utc_now()
    if status.get("first_tee_at_utc"):
        try:
            remaining = (
                parse_iso(str(status["first_tee_at_utc"])) - now
            ).total_seconds()
            status["time_remaining_seconds"] = int(remaining)
        except (ValueError, TypeError):
            status["time_remaining_seconds"] = None
    paths.status_path.parent.mkdir(parents=True, exist_ok=True)
    paths.status_path.write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def weekly_forecast(
    paths: WeeklyPaths,
    now: Optional[datetime] = None,
    dry_run: bool = False,
    forecast_due_hours_before: int = FORECAST_DUE_HOURS_BEFORE,
    schedule_html: Optional[str] = None,
    schedule_url: str = DEFAULT_SCHEDULE_URL,
    simulations: int = 20_000,
    top_n: int = 25,
) -> tuple[int, dict[str, Any]]:
    now = now or utc_now()
    status = _base_status(now, forecast_due_hours_before, dry_run)

    try:
        ec, key = _load_or_discover(
            paths, now, schedule_html, schedule_url
        )
    except CurrentEventDiscoveryError as exc:
        status["state"] = STATE_BLOCKED
        status["blocking_reason"] = f"discovery failed: {exc}"
        status["last_error"] = str(exc)
        _finalize(paths, status, None)
        return EXIT_ERROR, status
    except NoNextEventError as exc:
        status["state"] = "no_event"
        status["blocking_reason"] = str(exc)
        status["last_error"] = str(exc)
        _finalize(paths, status, None)
        return EXIT_WAITING, status
    except WeeklyForecastError as exc:
        status["state"] = STATE_BLOCKED
        status["blocking_reason"] = str(exc)
        status["last_error"] = str(exc)
        _finalize(paths, status, None)
        return EXIT_BLOCKED, status
    _set_key(ec, key)

    players_rows = _load_players(paths)

    if ec.state in {STATE_DISCOVERED, STATE_AWAITING_FIELD}:
        result = _try_field(paths, ec, now)
        status["field_cross_check_size"] = result.get("cross_check_size")
        ec.save(paths.event_control_path(ec.event_key))
        if not result["ready"]:
            status["field_ready"] = False
            status["blocking_reason"] = result["reason"]
            _finalize(paths, status, ec)
            return EXIT_WAITING, status

    if ec.state in {
        STATE_AWAITING_TEE_TIMES,
        STATE_AWAITING_IDENTITY,
        STATE_FORECAST_READY,
    }:
        ready = _apply_tee_times(paths, ec, now, forecast_due_hours_before)
        if not ready:
            status["field_ready"] = True
            status["blocking_reason"] = "awaiting reviewed tee-time evidence"
            _finalize(paths, status, ec)
            return EXIT_WAITING, status

    if ec.state in {STATE_AWAITING_IDENTITY, STATE_FORECAST_READY}:
        ok = _apply_identity(paths, ec, now, players_rows)
        audit_path = paths.identity_audit_path(ec.event_key)
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        status["identity_matched"] = int(
            audit.get("match_status_counts", {}).get("matched", 0)
        ) + int(
            audit.get("match_status_counts", {}).get("matched_no_prior_rounds", 0)
        )
        status["identity_problems"] = audit.get("problems", [])
        if not ok:
            _finalize(paths, status, ec)
            return EXIT_IDENTITY_BLOCKED, status

    if ec.state == STATE_FORECAST_READY:
        first_tee = parse_iso(str(ec.first_tee_at_utc))
        due = parse_iso(str(ec.forecast_due_at_utc))
        if now >= first_tee:
            ec.transition(STATE_DEADLINE_MISSED, "first tee passed", now)
            ec.save(paths.event_control_path(ec.event_key))
            _finalize(paths, status, ec)
            return EXIT_DEADLINE_MISSED, status
        if now < due:
            status["blocking_reason"] = "forecast not due yet"
            _finalize(paths, status, ec)
            return EXIT_WAITING, status
        if dry_run:
            status["blocking_reason"] = "dry_run: forecast not executed"
            _finalize(paths, status, ec)
            return EXIT_WAITING, status
        try:
            result = _run_forecast(paths, ec, now, simulations, top_n)
        except WeeklyForecastError as exc:
            status["state"] = STATE_BLOCKED
            status["blocking_reason"] = str(exc)
            status["last_error"] = str(exc)
            _finalize(paths, status, ec)
            return EXIT_BLOCKED, status
        if not result.get("archived"):
            _finalize(paths, status, ec)
            return EXIT_BLOCKED, status

    _finalize(paths, status, ec)
    return EXIT_WAITING, status


def weekly_forecast_status(paths: WeeklyPaths) -> dict[str, Any]:
    if not paths.status_path.exists():
        return {"state": "no_status", "blocking_reason": "status file not created yet"}
    try:
        value = json.loads(paths.status_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"state": "invalid_status"}
    return value
