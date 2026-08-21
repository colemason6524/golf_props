"""Verification of immutable prospective forecast archives."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from golf_props.ingestion.current_field import sha256_file

ARCHIVE_SCHEMA_VERSION = 1

REQUIRED_ARCHIVE_FILES = [
    "event.json",
    "field.csv",
    "field_raw.csv",
    "field_source_manifest.json",
    "tee_times.csv",
    "tee_time_source_manifest.json",
    "structure_decision.json",
    "identity_audit.json",
    "strengths.csv",
    "predictions.csv",
    "report.md",
    "run_manifest.json",
    "archive_manifest.json",
]


class ForecastArchiveError(ValueError):
    """Raised when a forecast archive is missing or corrupt."""


def archive_manifest(archive_dir: Path) -> dict[str, Any]:
    path = archive_dir / "archive_manifest.json"
    if not path.exists():
        raise ForecastArchiveError(
            f"archive missing archive_manifest.json: {archive_dir}"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ForecastArchiveError(
            f"invalid archive manifest: {path}"
        ) from exc
    if not isinstance(value, dict) or not isinstance(value.get("files"), dict):
        raise ForecastArchiveError(f"malformed archive manifest: {path}")
    return value


def verify_forecast_archive(archive_dir: Path) -> dict[str, Any]:
    if not archive_dir.exists():
        raise ForecastArchiveError(f"archive directory missing: {archive_dir}")
    manifest = archive_manifest(archive_dir)
    hashes = manifest["files"]
    problems: list[str] = []
    for name in REQUIRED_ARCHIVE_FILES:
        path = archive_dir / name
        if not path.exists():
            problems.append(f"missing_required:{name}")
    for name in sorted(hashes):
        path = archive_dir / name
        if not path.exists():
            problems.append(f"missing_file:{name}")
            continue
        if sha256_file(path) != str(hashes[name]):
            problems.append(f"hash_mismatch:{name}")
    actual_files = {path.name for path in archive_dir.iterdir() if path.is_file()}
    expected_files = set(hashes)
    for name in sorted(actual_files - expected_files - {"archive_manifest.json"}):
        problems.append(f"unexpected_file:{name}")
    run_manifest_path = archive_dir / "run_manifest.json"
    if run_manifest_path.exists():
        try:
            run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
            artifact_hashes = run_manifest.get("artifact_sha256", {})
            for key in ("strengths", "predictions", "report"):
                expected = artifact_hashes.get(key)
                path = archive_dir / f"{key}.csv" if key != "report" else archive_dir / "report.md"
                if expected and path.exists() and sha256_file(path) != expected:
                    problems.append(f"run_manifest_hash_mismatch:{key}")
        except (json.JSONDecodeError, OSError):
            problems.append("invalid_run_manifest")
    return {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "archive_dir": str(archive_dir),
        "verified": not problems,
        "problems": problems,
    }
