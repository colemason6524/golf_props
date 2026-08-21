import json
from pathlib import Path

import pytest

from golf_props.backtest.forecast_archive import (
    ForecastArchiveError,
    verify_forecast_archive,
)


def build_archive(tmp_path, tamper=None, missing=None):
    archive = tmp_path / "archive"
    archive.mkdir(parents=True)
    for name in [
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
    ]:
        (archive / name).write_text(name, encoding="utf-8")
    (archive / "run_manifest.json").write_text(
        json.dumps(
            {
                "artifact_sha256": {
                    "strengths": "",
                    "predictions": "",
                    "report": "",
                }
            }
        ),
        encoding="utf-8",
    )
    files = {
        name: _sha(archive / name)
        for name in sorted(p.name for p in archive.iterdir())
    }
    (archive / "archive_manifest.json").write_text(
        json.dumps({"schema_version": 1, "files": files}, indent=2),
        encoding="utf-8",
    )
    if tamper:
        (archive / tamper).write_text("tampered", encoding="utf-8")
    if missing:
        (archive / missing).unlink()
    return archive


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_verify_clean_archive(tmp_path):
    archive = build_archive(tmp_path)
    result = verify_forecast_archive(archive)
    assert result["verified"] is True
    assert result["problems"] == []


def test_verify_tampered_archive(tmp_path):
    archive = build_archive(tmp_path, tamper="predictions.csv")
    result = verify_forecast_archive(archive)
    assert result["verified"] is False
    assert any("hash_mismatch" in problem for problem in result["problems"])


def test_verify_missing_required_file(tmp_path):
    archive = build_archive(tmp_path, missing="strengths.csv")
    result = verify_forecast_archive(archive)
    assert result["verified"] is False
    assert any("missing_required:strengths.csv" in problem for problem in result["problems"])


def test_verify_unexpected_file(tmp_path):
    archive = build_archive(tmp_path)
    (archive / "extra.txt").write_text("x", encoding="utf-8")
    result = verify_forecast_archive(archive)
    assert result["verified"] is False
    assert any("unexpected_file:extra.txt" in problem for problem in result["problems"])


def test_verify_missing_archive_manifest(tmp_path):
    archive = build_archive(tmp_path)
    (archive / "archive_manifest.json").unlink()
    with pytest.raises(ForecastArchiveError, match="archive_manifest"):
        verify_forecast_archive(archive)
