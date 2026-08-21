"""Reviewed tee-time evidence ingestion and earliest-start derivation.

Tee times must come from preserved evidence with an explicit IANA local timezone
and reviewer. The derived earliest Round 1 tee time (across all starting holes)
becomes the authoritative first-tee UTC timestamp for the frozen forecast.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from golf_props.config import PROCESSED_DIR, RAW_DIR
from golf_props.ingestion.current_field import sha256_file

TEE_TIMES_ROOT = RAW_DIR / "current_events"
PROCESSED_TEE_TIMES_ROOT = PROCESSED_DIR / "current_events"
TEE_PAYLOAD_COLUMNS = {"player_name", "local_tee_datetime"}


class TeeTimeError(ValueError):
    """Raised when tee-time evidence cannot be ingested."""


@dataclass
class TeeTimeEvidence:
    event_key: str
    event_name: str
    org: str
    url: str
    captured_at_utc: str
    local_timezone: str
    reviewed_by: str
    payload_path: str
    payload_sha256: str
    rows: list[dict[str, str]] = field(default_factory=list)
    earliest_tee_at_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "event_key": self.event_key,
            "event_name": self.event_name,
            "org": self.org,
            "url": self.url,
            "captured_at_utc": self.captured_at_utc,
            "local_timezone": self.local_timezone,
            "reviewed_by": self.reviewed_by,
            "payload_path": self.payload_path,
            "payload_sha256": self.payload_sha256,
            "derived_rows": len(self.rows),
            "earliest_tee_at_utc": self.earliest_tee_at_utc,
        }


def parse_tee_time_payload(payload_path: Path) -> list[dict[str, str]]:
    with payload_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        missing = TEE_PAYLOAD_COLUMNS - headers
        if missing:
            raise TeeTimeError(
                f"tee-time payload missing required columns: {', '.join(sorted(missing))}"
            )
        rows = []
        for index, row in enumerate(reader, start=2):
            player_name = str(row.get("player_name") or "").strip()
            local = str(row.get("local_tee_datetime") or "").strip()
            if not player_name or not local:
                raise TeeTimeError(
                    f"tee-time payload row {index} missing player_name or local time"
                )
            rows.append(
                {
                    "player_name": player_name,
                    "local_tee_datetime": local,
                    "starting_hole": str(row.get("starting_hole") or "").strip(),
                }
            )
        if not rows:
            raise TeeTimeError("tee-time payload is empty")
        return rows


def derive_earliest_tee_utc(
    payload_rows: list[dict[str, str]],
    local_timezone: str,
) -> tuple[str, int]:
    try:
        zone = ZoneInfo(local_timezone)
    except ZoneInfoNotFoundError as exc:
        raise TeeTimeError(f"unknown IANA timezone: {local_timezone}") from exc
    parsed = []
    for row in payload_rows:
        try:
            local_dt = datetime.strptime(row["local_tee_datetime"], "%Y-%m-%d %H:%M")
        except ValueError as exc:
            raise TeeTimeError(
                f"unparseable local tee time {row['local_tee_datetime']!r}"
            ) from exc
        parsed.append(local_dt.replace(tzinfo=zone))
    if not parsed:
        raise TeeTimeError("no parseable tee times")
    earliest = min(parsed)
    return (
        earliest.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z"),
        len(parsed),
    )


def import_tee_time_evidence(
    event_key: str,
    event_name: str,
    payload_path: Path,
    org: str,
    url: str,
    captured_at_utc: str,
    local_timezone: str,
    reviewed_by: str,
    raw_root: Path = TEE_TIMES_ROOT,
) -> TeeTimeEvidence:
    rows = parse_tee_time_payload(payload_path)
    earliest_utc, derived_count = derive_earliest_tee_utc(rows, local_timezone)
    evidence_dir = raw_root / event_key / "tee_times" / "latest"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    stored = evidence_dir / payload_path.name
    shutil.copyfile(payload_path, stored)
    evidence = TeeTimeEvidence(
        event_key=event_key,
        event_name=event_name,
        org=org,
        url=url,
        captured_at_utc=captured_at_utc,
        local_timezone=local_timezone,
        reviewed_by=reviewed_by,
        payload_path=str(stored),
        payload_sha256=sha256_file(stored),
        rows=rows,
        earliest_tee_at_utc=earliest_utc,
    )
    (evidence_dir / "source_manifest.json").write_text(
        json.dumps(evidence.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def load_latest_tee_time_evidence(
    event_key: str,
    raw_root: Path = TEE_TIMES_ROOT,
) -> Optional[TeeTimeEvidence]:
    evidence_dir = raw_root / event_key / "tee_times" / "latest"
    manifest_path = evidence_dir / "source_manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    payload_path = Path(str(manifest.get("payload_path") or ""))
    if not payload_path.exists():
        return None
    try:
        rows = parse_tee_time_payload(payload_path)
    except TeeTimeError:
        return None
    return TeeTimeEvidence(
        event_key=str(manifest.get("event_key") or event_key),
        event_name=str(manifest.get("event_name") or ""),
        org=str(manifest.get("org") or ""),
        url=str(manifest.get("url") or ""),
        captured_at_utc=str(manifest.get("captured_at_utc") or ""),
        local_timezone=str(manifest.get("local_timezone") or ""),
        reviewed_by=str(manifest.get("reviewed_by") or ""),
        payload_path=str(payload_path),
        payload_sha256=str(manifest.get("payload_sha256") or ""),
        rows=rows,
        earliest_tee_at_utc=str(manifest.get("earliest_tee_at_utc") or ""),
    )


def write_tee_times_csv(
    path: Path,
    rows: list[dict[str, str]],
    earliest_tee_at_utc: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["earliest_tee_at_utc"])
        writer.writerow([earliest_tee_at_utc])
        writer.writerow([])
        writer.writerow(["player_name", "local_tee_datetime", "starting_hole"])
        for row in rows:
            writer.writerow(
                [
                    str(row.get("player_name") or ""),
                    str(row.get("local_tee_datetime") or ""),
                    str(row.get("starting_hole") or ""),
                ]
            )
