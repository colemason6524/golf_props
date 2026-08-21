import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from golf_props.backtest.forecast_archive import verify_forecast_archive
from golf_props.backtest.rolling_simulation_validation import file_sha256
from golf_props.features.round_performance import build_round_performance
from golf_props.ingestion.current_field import (
    FINALITY_FINAL,
    SOURCE_KIND_OFFICIAL,
    import_field_evidence,
)
from golf_props.ingestion.tee_times import import_tee_time_evidence
from golf_props.normalization.bootstrap_results import normalize_file
from golf_props.pipelines import current_event_simulation as ces
from golf_props.pipelines import weekly_forecast as wf

FIXTURE = Path(__file__).parent / "fixtures" / "sample_pga_results.csv"
SCHEDULE = Path(__file__).parent / "fixtures" / "cbs_schedule_only_one.html"

KEY = "test_invitational_2025"


def freeze_clock(monkeypatch, iso):
    current = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    monkeypatch.setattr(wf, "utc_now", lambda: current)
    monkeypatch.setattr(ces, "utc_now", lambda: current)
    return current


def prepare_paths(tmp_path):
    canonical = tmp_path / "canonical"
    round_performance = tmp_path / "round_performance.csv"
    manifest = tmp_path / "manifest.json"
    normalize_file(FIXTURE, canonical)
    build_round_performance(canonical, round_performance)
    manifest.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "status": "frozen_awaiting_future_evaluation",
                "seed": 17,
                "cut_size": 2,
                "canonical_dir": str(canonical),
                "round_performance_path": str(round_performance),
                "input_sha256": {
                    "events": file_sha256(canonical / "events.csv"),
                    "player_event_results": file_sha256(
                        canonical / "player_event_results.csv"
                    ),
                    "round_performance": file_sha256(round_performance),
                },
                "frozen_model": {
                    "half_life_days": 365.0,
                    "prior_rounds": 8.0,
                    "variance_prior_rounds": 20.0,
                    "source_data_through": "2025-04-13",
                    "prospective_holdout_after": "2025-04-20",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    registry = tmp_path / "registry.csv"
    registry.write_text(
        "season,source_event_id,event_name,include,format,rounds,cut_rule,cut_size,decision_status,reviewed_at_utc,notes\n"
        "2025,,Test Invitational,1,72_hole_stroke_play,4,top_n_and_ties,65,reviewed,2025-01-01T00:00:00Z,\n",
        encoding="utf-8",
    )
    paths = wf.WeeklyPaths(
        manifest=manifest,
        round_performance=round_performance,
        canonical_dir=canonical,
        aliases=Path("config/player_aliases.csv"),
        registry=registry,
        weekly_dir=tmp_path / "weekly",
        raw_events_root=tmp_path / "raw_events",
        processed_events_root=tmp_path / "processed_events",
        archives_root=tmp_path / "archives",
        raw_schedule_dir=tmp_path / "schedule",
        bovada_snapshot=tmp_path / "no_bovada.csv",
    )
    return paths


def import_field(tmp_path, paths, names=None, extra_rows=True):
    names = names or ["Scottie Scheffler", "Rory McIlroy"]
    lines = ["player_name,player_id,entry_status"]
    lines += [f"{name},,confirmed" for name in names]
    payload = tmp_path / "field.csv"
    payload.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return import_field_evidence(
        KEY,
        payload,
        source_kind=SOURCE_KIND_OFFICIAL,
        org="official_test",
        url="https://example.com/field",
        captured_at_utc="2025-04-29T00:00:00Z",
        finality=FINALITY_FINAL,
        event_name="Test Invitational",
        expected_field_size=len(names),
        raw_root=paths.raw_events_root,
    )


def import_tee(tmp_path, paths):
    payload = tmp_path / "tee.csv"
    payload.write_text(
        "player_name,local_tee_datetime,starting_hole\n"
        "Scottie Scheffler,2025-05-01 07:12,1\n"
        "Rory McIlroy,2025-05-01 07:00,10\n",
        encoding="utf-8",
    )
    return import_tee_time_evidence(
        KEY,
        "Test Invitational",
        payload,
        org="official_test",
        url="https://example.com/teetimes",
        captured_at_utc="2025-04-30T00:00:00Z",
        local_timezone="America/New_York",
        reviewed_by="operator",
        raw_root=paths.raw_events_root,
    )


def test_weekly_forecast_waits_for_field(tmp_path, monkeypatch):
    paths = prepare_paths(tmp_path)
    freeze_clock(monkeypatch, "2025-04-30T12:00:00Z")
    exit_code, status = wf.weekly_forecast(
        paths, schedule_html=SCHEDULE.read_text(encoding="utf-8")
    )
    assert exit_code == wf.EXIT_WAITING
    assert status["state"] == wf.STATE_AWAITING_FIELD
    assert status["event_key"] == KEY

    import_field(tmp_path, paths)
    exit_code, status = wf.weekly_forecast(
        paths, schedule_html=SCHEDULE.read_text(encoding="utf-8")
    )
    assert status["state"] == wf.STATE_AWAITING_TEE_TIMES
    assert exit_code == wf.EXIT_WAITING

    import_tee(tmp_path, paths)
    exit_code, status = wf.weekly_forecast(
        paths, schedule_html=SCHEDULE.read_text(encoding="utf-8")
    )
    assert status["state"] == wf.STATE_FORECAST_READY
    assert status["first_tee_at_utc"] == "2025-05-01T11:00:00Z"
    assert exit_code == wf.EXIT_WAITING


def test_weekly_forecast_archives_immutable_primary(tmp_path, monkeypatch):
    paths = prepare_paths(tmp_path)
    import_field(tmp_path, paths)
    import_tee(tmp_path, paths)
    freeze_clock(monkeypatch, "2025-04-30T23:30:00Z")
    exit_code, status = wf.weekly_forecast(
        paths, schedule_html=SCHEDULE.read_text(encoding="utf-8")
    )
    assert exit_code == wf.EXIT_WAITING
    assert status["state"] == wf.STATE_FORECAST_ARCHIVED
    archive = paths.archive_dir(KEY)
    assert archive.exists()
    assert (archive / "run_manifest.json").exists()
    for name in [
        "event.json",
        "field.csv",
        "field_source_manifest.json",
        "tee_times.csv",
        "tee_time_source_manifest.json",
        "structure_decision.json",
        "identity_audit.json",
        "strengths.csv",
        "predictions.csv",
        "report.md",
    ]:
        assert (archive / name).exists(), name
    result = verify_forecast_archive(archive)
    assert result["verified"] is True, result["problems"]

    run_manifest = json.loads((archive / "run_manifest.json").read_text())
    assert run_manifest["eligibility"]["classification"] == "prospective_forecast"
    assert run_manifest["event_structure"]["cut_rule"] == "top_n_and_ties"
    assert run_manifest["completed_at_utc"]

    second_exit, second_status = wf.weekly_forecast(
        paths, schedule_html=SCHEDULE.read_text(encoding="utf-8")
    )
    assert second_exit == wf.EXIT_WAITING
    assert second_status["state"] == wf.STATE_FORECAST_ARCHIVED
    assert verify_forecast_archive(archive)["verified"] is True


def test_weekly_forecast_waits_until_due(tmp_path, monkeypatch):
    paths = prepare_paths(tmp_path)
    import_field(tmp_path, paths)
    import_tee(tmp_path, paths)
    freeze_clock(monkeypatch, "2025-04-30T22:00:00Z")
    exit_code, status = wf.weekly_forecast(
        paths, schedule_html=SCHEDULE.read_text(encoding="utf-8")
    )
    assert exit_code == wf.EXIT_WAITING
    assert status["state"] == wf.STATE_FORECAST_READY
    assert not paths.archive_dir(KEY).exists()


def test_weekly_forecast_dry_run_does_not_archive(tmp_path, monkeypatch):
    paths = prepare_paths(tmp_path)
    import_field(tmp_path, paths)
    import_tee(tmp_path, paths)
    freeze_clock(monkeypatch, "2025-04-30T23:30:00Z")
    exit_code, status = wf.weekly_forecast(
        paths,
        schedule_html=SCHEDULE.read_text(encoding="utf-8"),
        dry_run=True,
    )
    assert exit_code == wf.EXIT_WAITING
    assert status["dry_run"] is True
    assert not paths.archive_dir(KEY).exists()


def test_weekly_forecast_deadline_missed(tmp_path, monkeypatch):
    paths = prepare_paths(tmp_path)
    import_field(tmp_path, paths)
    import_tee(tmp_path, paths)
    freeze_clock(monkeypatch, "2025-05-01T11:00:00Z")
    exit_code, status = wf.weekly_forecast(
        paths, schedule_html=SCHEDULE.read_text(encoding="utf-8")
    )
    assert exit_code == wf.EXIT_DEADLINE_MISSED
    assert status["state"] == wf.STATE_DEADLINE_MISSED
    assert not paths.archive_dir(KEY).exists()


def test_weekly_forecast_identity_blocked(tmp_path, monkeypatch):
    paths = prepare_paths(tmp_path)
    import_field(tmp_path, paths, names=["Scottie Scheffler", "New Player"])
    import_tee(tmp_path, paths)
    freeze_clock(monkeypatch, "2025-04-30T23:30:00Z")
    exit_code, status = wf.weekly_forecast(
        paths, schedule_html=SCHEDULE.read_text(encoding="utf-8")
    )
    assert exit_code == wf.EXIT_IDENTITY_BLOCKED
    assert status["state"] == wf.STATE_BLOCKED
    assert any("New Player" in problem for problem in status["identity_problems"])
    assert not paths.archive_dir(KEY).exists()


def test_weekly_forecast_blocks_unknown_event_structure(tmp_path, monkeypatch):
    paths = prepare_paths(tmp_path)
    paths.registry.write_text(
        "season,source_event_id,event_name,include,format,rounds,cut_rule,cut_size,decision_status,reviewed_at_utc,notes\n",
        encoding="utf-8",
    )
    freeze_clock(monkeypatch, "2025-04-30T12:00:00Z")
    exit_code, status = wf.weekly_forecast(
        paths, schedule_html=SCHEDULE.read_text(encoding="utf-8")
    )
    assert exit_code == wf.EXIT_BLOCKED
    assert "no next event selected" in status["blocking_reason"]


def test_status_file_written_each_run(tmp_path, monkeypatch):
    paths = prepare_paths(tmp_path)
    freeze_clock(monkeypatch, "2025-04-30T12:00:00Z")
    wf.weekly_forecast(paths, schedule_html=SCHEDULE.read_text(encoding="utf-8"))
    status = wf.weekly_forecast_status(paths)
    assert status["state"] == wf.STATE_AWAITING_FIELD
    assert status["last_attempt_at_utc"]
