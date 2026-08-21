"""Authoritative field evidence ingestion for the weekly forecast.

Only a preserved official field (source_kind="official") with finality "final"
can unlock a forecast. Sportsbook and news sources are cross-checks only and can
never authorize the performance-model field of record.
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

from golf_props.config import PROCESSED_DIR, RAW_DIR

FIELDS_ROOT = RAW_DIR / "current_events"
PROCESSED_ROOT = PROCESSED_DIR / "current_events"
SOURCE_KIND_OFFICIAL = "official"
SOURCE_KIND_CROSS_CHECK = "cross_check"
FINALITY_FINAL = "final"
FINALITY_PRELIMINARY = "preliminary"
FIELD_REQUIRED_COLUMNS = {"player_name"}
FIELD_OPTIONAL_COLUMNS = {"player_id", "entry_status"}


class CurrentFieldError(ValueError):
    """Raised when field evidence cannot be ingested."""


@dataclass
class FieldEvidence:
    event_key: str
    event_name: str
    source_kind: str
    org: str
    url: str
    captured_at_utc: str
    finality: str
    expected_field_size: Optional[int]
    payload_path: str
    payload_sha256: str
    rows: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "event_key": self.event_key,
            "event_name": self.event_name,
            "source_kind": self.source_kind,
            "org": self.org,
            "url": self.url,
            "captured_at_utc": self.captured_at_utc,
            "finality": self.finality,
            "expected_field_size": self.expected_field_size,
            "payload_path": self.payload_path,
            "payload_sha256": self.payload_sha256,
            "parsed_rows": len(self.rows),
        }

    def ready(self) -> bool:
        return self.source_kind == SOURCE_KIND_OFFICIAL and (
            self.finality == FINALITY_FINAL
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_field_payload(payload_path: Path) -> list[dict[str, str]]:
    with payload_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        missing = FIELD_REQUIRED_COLUMNS - headers
        if missing:
            raise CurrentFieldError(
                f"field payload missing required columns: {', '.join(sorted(missing))}"
            )
        rows = []
        seen: set[str] = set()
        for index, row in enumerate(reader, start=2):
            player_name = str(row.get("player_name") or "").strip()
            if not player_name:
                raise CurrentFieldError(f"field payload row {index} missing player_name")
            key = player_name.casefold()
            if key in seen:
                raise CurrentFieldError(
                    f"field payload has duplicate player_name: {player_name}"
                )
            seen.add(key)
            rows.append(
                {
                    "player_name": player_name,
                    "player_id": str(row.get("player_id") or "").strip(),
                    "entry_status": str(row.get("entry_status") or "confirmed").strip(),
                }
            )
        if not rows:
            raise CurrentFieldError("field payload is empty")
        return rows


def import_field_evidence(
    event_key: str,
    payload_path: Path,
    source_kind: str,
    org: str,
    url: str,
    captured_at_utc: str,
    finality: str,
    event_name: str,
    expected_field_size: Optional[int] = None,
    raw_root: Path = FIELDS_ROOT,
) -> FieldEvidence:
    if source_kind not in {SOURCE_KIND_OFFICIAL, SOURCE_KIND_CROSS_CHECK}:
        raise CurrentFieldError(f"unsupported source_kind: {source_kind}")
    if finality not in {FINALITY_FINAL, FINALITY_PRELIMINARY, "unknown"}:
        raise CurrentFieldError(f"unsupported finality: {finality}")
    rows = parse_field_payload(payload_path)
    evidence_dir = raw_root / event_key / "field" / "latest"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    stored = evidence_dir / payload_path.name
    shutil.copyfile(payload_path, stored)
    evidence = FieldEvidence(
        event_key=event_key,
        event_name=event_name,
        source_kind=source_kind,
        org=org,
        url=url,
        captured_at_utc=captured_at_utc,
        finality=finality,
        expected_field_size=expected_field_size,
        payload_path=str(stored),
        payload_sha256=sha256_file(stored),
        rows=rows,
    )
    (evidence_dir / "source_manifest.json").write_text(
        json.dumps(evidence.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def load_latest_field_evidence(
    event_key: str,
    raw_root: Path = FIELDS_ROOT,
) -> Optional[FieldEvidence]:
    evidence_dir = raw_root / event_key / "field" / "latest"
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
        rows = parse_field_payload(payload_path)
    except CurrentFieldError:
        return None
    return FieldEvidence(
        event_key=str(manifest.get("event_key") or event_key),
        event_name=str(manifest.get("event_name") or ""),
        source_kind=str(manifest.get("source_kind") or ""),
        org=str(manifest.get("org") or ""),
        url=str(manifest.get("url") or ""),
        captured_at_utc=str(manifest.get("captured_at_utc") or ""),
        finality=str(manifest.get("finality") or ""),
        expected_field_size=manifest.get("expected_field_size"),
        payload_path=str(payload_path),
        payload_sha256=str(manifest.get("payload_sha256") or ""),
        rows=rows,
    )


def write_field_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["player_id", "player_name", "entry_status"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "player_id": str(row.get("player_id") or "").strip(),
                    "player_name": str(row.get("player_name") or "").strip(),
                    "entry_status": str(row.get("entry_status") or "confirmed").strip(),
                }
            )


def bovada_field_cross_check(odds_csv_path: Path) -> dict[str, Any]:
    """Candidate field diagnostics from the latest Bovada snapshot (cross-check)."""
    if not odds_csv_path.exists():
        return {"available": False, "field_size": None, "player_names": []}
    with odds_csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if "player_name" not in (reader.fieldnames or []):
            return {"available": True, "field_size": None, "player_names": []}
        names: list[str] = []
        seen: set[str] = set()
        for row in reader:
            name = str(row.get("player_name") or "").strip()
            key = name.casefold()
            if name and key not in seen:
                seen.add(key)
                names.append(name)
    return {"available": True, "field_size": len(names), "player_names": names}
