import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

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


def test_automated_field_collection_uses_raw_events_root_keyword(tmp_path, monkeypatch):
    paths = prepare_paths(tmp_path)
    ec = wf.EventControl(
        event_key=KEY,
        event_name="Test Invitational",
        season=2025,
        state=wf.STATE_DISCOVERED,
    )
    collected = object()
    evidence = SimpleNamespace(
        rows=[
            {
                "player_name": "Scottie Scheffler",
                "player_id": "",
                "entry_status": "confirmed",
            }
        ],
        expected_field_size=1,
        ready=lambda: True,
        to_dict=lambda: {"source_kind": "official", "finality": "final"},
    )

    monkeypatch.setattr(
        wf,
        "lookup_tournament_id",
        lambda _event_name, _season: ("R2025999", "test-invitational", "May 1 - 4, 2025", "America/New_York"),
    )
    monkeypatch.setattr(wf, "collect_pga_tour_field", lambda **_: collected)

    def persist_field(value, *, raw_events_root):
        assert value is collected
        assert raw_events_root == paths.raw_events_root
        return evidence

    monkeypatch.setattr(wf, "persist_field_evidence", persist_field)

    result = wf._try_field(paths, ec, datetime(2025, 4, 30, 12, tzinfo=timezone.utc))

    assert result["ready"] is True
    assert ec.state == wf.STATE_AWAITING_TEE_TIMES


def test_automated_tee_time_collection_uses_raw_events_root_keyword(tmp_path, monkeypatch):
    paths = prepare_paths(tmp_path)
    ec = wf.EventControl(
        event_key=KEY,
        event_name="Test Invitational",
        season=2025,
        pga_tour_tournament_id="R2025999",
        state=wf.STATE_AWAITING_TEE_TIMES,
    )
    collected = SimpleNamespace(earliest_tee_at_utc="2025-05-01T11:00:00Z")
    evidence = SimpleNamespace(
        rows=[
            {
                "player_name": "Scottie Scheffler",
                "local_tee_datetime": "2025-05-01 07:00",
                "starting_hole": "1",
            }
        ],
        earliest_tee_at_utc="2025-05-01T11:00:00Z",
        to_dict=lambda: {"source_kind": "official"},
    )

    monkeypatch.setattr(wf, "collect_pga_tour_tee_times", lambda **_: collected)

    def persist_tee(value, *, raw_events_root):
        assert value is collected
        assert raw_events_root == paths.raw_events_root
        return evidence

    monkeypatch.setattr(wf, "persist_tee_time_evidence", persist_tee)

    assert wf._apply_tee_times(
        paths,
        ec,
        datetime(2025, 4, 30, 12, tzinfo=timezone.utc),
        forecast_due_hours_before=12,
    ) is True
    assert ec.state == wf.STATE_AWAITING_IDENTITY


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


def test_weekly_forecast_admits_unmatched_via_tour_prior(tmp_path, monkeypatch):
    paths = prepare_paths(tmp_path)
    import_field(tmp_path, paths, names=["Scottie Scheffler", "New Player"])
    import_tee(tmp_path, paths)
    freeze_clock(monkeypatch, "2025-04-30T23:30:00Z")
    exit_code, status = wf.weekly_forecast(
        paths, schedule_html=SCHEDULE.read_text(encoding="utf-8")
    )
    # A no-history player is admitted (blank id -> tour prior) instead of
    # blocking the whole event, so the archive is produced automatically.
    assert exit_code == wf.EXIT_WAITING
    assert status["state"] == wf.STATE_FORECAST_ARCHIVED
    assert "New Player" in status["identity_unmatched_admitted"]
    assert paths.archive_dir(KEY).exists()
    audit = json.loads(paths.identity_audit_path(KEY).read_text(encoding="utf-8"))
    assert audit["ok"] is True
    assert audit["problems"] == []


def test_weekly_forecast_identity_blocks_on_ambiguous(tmp_path, monkeypatch):
    from golf_props.normalization.player_identity import AMBIGUOUS, ResolvedPlayer

    paths = prepare_paths(tmp_path)
    import_field(tmp_path, paths, names=["Scottie Scheffler", "Rory McIlroy"])
    import_tee(tmp_path, paths)

    def fake_resolve(*_args, **_kwargs):
        resolved = [
            ResolvedPlayer("Scottie Scheffler", "p1", "confirmed", "matched"),
            ResolvedPlayer("Rory McIlroy", "", "confirmed", AMBIGUOUS),
        ]
        return resolved, {"warnings": []}

    monkeypatch.setattr(wf, "resolve_field_identities", fake_resolve)
    freeze_clock(monkeypatch, "2025-04-30T23:30:00Z")
    exit_code, status = wf.weekly_forecast(
        paths, schedule_html=SCHEDULE.read_text(encoding="utf-8")
    )
    # Ambiguous identities still fail closed (never silently guessed).
    assert exit_code == wf.EXIT_IDENTITY_BLOCKED
    assert status["state"] == wf.STATE_BLOCKED
    assert not paths.archive_dir(KEY).exists()


def test_weekly_forecast_auto_includes_ordinary_event_without_registry(tmp_path, monkeypatch):
    paths = prepare_paths(tmp_path)
    paths.registry.write_text(
        "season,source_event_id,event_name,include,format,rounds,cut_rule,cut_size,decision_status,reviewed_at_utc,notes\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(wf, "lookup_tournament_id", lambda *_: None)
    freeze_clock(monkeypatch, "2025-04-30T12:00:00Z")
    exit_code, status = wf.weekly_forecast(
        paths, schedule_html=SCHEDULE.read_text(encoding="utf-8")
    )
    # An ordinary stroke-play event is now auto-included with a logged default
    # structure instead of blocking on a missing reviewed registry row.
    assert exit_code == wf.EXIT_WAITING
    assert status["state"] == wf.STATE_AWAITING_FIELD
    assert status["event_key"] == KEY
    assert status["structure_source"] == "auto_default_policy"
    assert status["structure"]["cut_rule"] == "top_n_and_ties"


TEAM_SCHEDULE = """<html><body>
<script type="application/ld+json">
{"@type": "SportsEvent", "name": "Presidents Cup", "sport": "golf", "url": "https://www.cbssports.com/golf/leaderboard/pga-tour/55555/presidents-cup", "startDate": "May 1, 2025", "endDate": "May 4, 2025", "location": {"name": "Quail Hollow", "address": {"addressLocality": "Charlotte", "addressRegion": "NC", "addressCountry": "USA"}}}
</script>
</body></html>
"""


def test_weekly_forecast_skips_team_event_without_registry(tmp_path, monkeypatch):
    paths = prepare_paths(tmp_path)
    paths.registry.write_text(
        "season,source_event_id,event_name,include,format,rounds,cut_rule,cut_size,decision_status,reviewed_at_utc,notes\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(wf, "lookup_tournament_id", lambda *_: None)
    freeze_clock(monkeypatch, "2025-04-30T12:00:00Z")
    exit_code, status = wf.weekly_forecast(
        paths, schedule_html=TEAM_SCHEDULE
    )
    # A team event with no reviewed row is never modelled as stroke play; it is
    # recorded as skipped and the run advances (no archive, no board).
    assert exit_code == wf.EXIT_BLOCKED
    skipped_names = [item["event_name"] for item in status.get("skipped", [])]
    assert "Presidents Cup" in skipped_names
    assert not paths.archive_dir("presidents_cup_2025").exists()


def test_weekly_forecast_skips_past_event_and_selects_next(tmp_path, monkeypatch):
    paths = prepare_paths(tmp_path)
    # Seed a finished, un-archived Biltmore-style event already past its start.
    from golf_props.events.event_control import STATE_AWAITING_FIELD as AW

    stale = wf.EventControl(
        event_key="stale_open_2025",
        event_name="Stale Open",
        season=2025,
        schedule_start_date="2025-04-10",
        competitive_start_date="2025-04-10",
        state=AW,
        created_at_utc="2025-04-01T00:00:00Z",
        updated_at_utc="2025-04-01T00:00:00Z",
    )
    stale.save(paths.event_control_path("stale_open_2025"))
    paths.pointer_path.write_text("stale_open_2025", encoding="utf-8")
    monkeypatch.setattr(wf, "lookup_tournament_id", lambda *_: None)
    # now is 2025-04-30, after Stale Open and on/before Test Invitational (May 1)
    freeze_clock(monkeypatch, "2025-04-30T12:00:00Z")
    exit_code, status = wf.weekly_forecast(
        paths, schedule_html=SCHEDULE.read_text(encoding="utf-8")
    )
    # The scheduler must not stay pinned to the finished event; it advances.
    assert paths.event_control_path("stale_open_2025").exists()
    stale_after = wf.EventControl.load(paths.event_control_path("stale_open_2025"))
    assert stale_after.state == wf.STATE_DEADLINE_MISSED
    assert status["event_key"] == KEY


def test_weekly_forecast_auto_includes_playoff_no_cut(tmp_path, monkeypatch):
    paths = prepare_paths(tmp_path)
    paths.registry.write_text(
        "season,source_event_id,event_name,include,format,rounds,cut_rule,cut_size,decision_status,reviewed_at_utc,notes\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(wf, "lookup_tournament_id", lambda *_: None)
    freeze_clock(monkeypatch, "2025-04-30T12:00:00Z")
    # Playoff event starts first; without a registry row it must be auto-included
    # under the explicit no_cut rule (never withheld, never given a guessed cut).
    playoff_schedule = """<html><body>
<script type="application/ld+json">
{"@type": "SportsEvent", "name": "TOUR Championship", "sport": "golf", "url": "https://www.cbssports.com/golf/leaderboard/pga-tour/44444/tour-championship", "startDate": "May 1, 2025", "endDate": "May 4, 2025", "location": {"name": "East Lake", "address": {"addressLocality": "Atlanta", "addressRegion": "GA", "addressCountry": "USA"}}}
</script>
<script type="application/ld+json">
{"@type": "SportsEvent", "name": "Test Invitational", "sport": "golf", "url": "https://www.cbssports.com/golf/leaderboard/pga-tour/12345/test-invitational", "startDate": "Sep 17, 2025", "endDate": "Sep 20, 2025", "location": {"name": "Example Golf Club", "address": {"addressLocality": "Springfield", "addressRegion": "OH", "addressCountry": "USA"}}}
</script>
</body></html>
"""
    exit_code, status = wf.weekly_forecast(paths, schedule_html=playoff_schedule)
    assert status["event_key"] == "tour_championship_2025"
    assert status["structure"]["cut_rule"] == "no_cut"
    assert status["structure"]["cut_size"] == 0
    assert status["structure_source"] == "auto_playoff_no_cut"


def test_status_file_written_each_run(tmp_path, monkeypatch):
    paths = prepare_paths(tmp_path)
    freeze_clock(monkeypatch, "2025-04-30T12:00:00Z")
    wf.weekly_forecast(paths, schedule_html=SCHEDULE.read_text(encoding="utf-8"))
    status = wf.weekly_forecast_status(paths)
    assert status["state"] == wf.STATE_AWAITING_FIELD
    assert status["last_attempt_at_utc"]


def test_autonomous_pga_path_archives_without_manual_inputs(tmp_path, monkeypatch):
    """No registry row, no manual field, no exact tee times, no operator action."""
    from golf_props.ingestion.pga_tour_collector import CollectedField

    paths = prepare_paths(tmp_path)
    paths.registry.write_text(
        "season,source_event_id,event_name,include,format,rounds,cut_rule,cut_size,decision_status,reviewed_at_utc,notes\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        wf,
        "lookup_tournament_id",
        lambda *_: ("R2025999", "test-invitational", "May 1 - 4, 2025", "America/New_York"),
    )

    def fake_collect_field(**_kwargs):
        return CollectedField(
            event_key=KEY,
            event_name="Test Invitational",
            tournament_id="R2025999",
            url="https://www.pgatour.com/tournaments/2025/test-invitational/R2025999/field",
            captured_at_utc="2025-04-28T12:00:00Z",
            raw_html_path=str(tmp_path / "raw_field.html"),
            raw_html_sha256="0" * 64,
            players=[
                {"player_name": "Scottie Scheffler", "player_id": "9001", "entry_status": "confirmed"},
                {"player_name": "Rory McIlroy", "player_id": "9002", "entry_status": "confirmed"},
            ],
            field_size=2,
        )

    monkeypatch.setattr(wf, "collect_pga_tour_field", fake_collect_field)
    monkeypatch.setattr(wf, "collect_pga_tour_tee_times", lambda **_: None)

    freeze_clock(monkeypatch, "2025-04-30T12:00:00Z")
    exit_code, status = wf.weekly_forecast(
        paths, schedule_html=SCHEDULE.read_text(encoding="utf-8")
    )

    assert exit_code == wf.EXIT_WAITING
    assert status["state"] == wf.STATE_FORECAST_ARCHIVED
    archive = paths.archive_dir(KEY)
    assert archive.exists()

    run_manifest = json.loads((archive / "run_manifest.json").read_text())
    # Source-namespace ids resolved by name to canonical ids, so the field is real.
    assert run_manifest["eligibility"]["classification"] == "prospective_forecast"
    assert run_manifest["timing_source"] == "schedule_date_fallback"
    assert run_manifest["event_structure"]["cut_rule"] == "top_n_and_ties"

    # The archive carries no fabricated tee times but records timing provenance.
    provenance = json.loads((archive / "timing_provenance.json").read_text())
    assert provenance["timing_source"] == "schedule_date_fallback"
    resolved_field = list(csv.DictReader((archive / "field.csv").open()))
    resolved_ids = {row["player_id"] for row in resolved_field}
    assert resolved_ids and "9001" not in resolved_ids and "9002" not in resolved_ids

    health = json.loads((paths.weekly_dir / "health.json").read_text())
    assert health["last_success_archive"]["event_key"] == KEY


def test_tee_time_fallback_not_disabled_by_prior_due(tmp_path, monkeypatch):
    """Regression: forecast_ready + missing tee times must still fall back.

    The Bank of Utah Championship 2026 deadlock: a fallback due time from a
    previous run made `_apply_tee_times` skip the official-start fallback and
    return False forever, so an overdue forecast never archived.
    """
    from golf_props.events.event_control import EventControl

    paths = prepare_paths(tmp_path)
    ec = EventControl(
        event_key=KEY,
        event_name="Test Invitational",
        season=2025,
        state=wf.STATE_FORECAST_READY,
        first_tee_at_utc="2025-05-01T04:00:00Z",
        official_start_at_utc="2025-05-01T04:00:00Z",
        forecast_due_at_utc="2025-04-30T06:00:00Z",
    )
    ec.save(paths.event_control_path(KEY))
    # No tee-time evidence and automated collection provides nothing.
    monkeypatch.setattr(wf, "load_latest_tee_time_evidence", lambda *_a, **_k: None)
    monkeypatch.setattr(wf, "collect_pga_tour_tee_times", lambda **_k: None)

    ready = wf._apply_tee_times(paths, ec, wf.utc_now(), 12)

    assert ready is True
    assert ec.forecast_due_at_utc == "2025-04-30T06:00:00Z"
    assert ec.first_tee_at_utc == "2025-05-01T04:00:00Z"


def test_identify_reversed_last_first_names(tmp_path):
    """Regression: PGA TOUR collector emits "Last, First" names."""
    from golf_props.normalization.player_identity import (
        build_canonical_index,
        resolve_field_identities,
    )

    players_rows = [
        {"player_id": "c1", "player_name": "Kihei Akina"},
        {"player_id": "c2", "player_name": "Tony Finau"},
    ]
    field_rows = [
        {"player_id": "67118", "player_name": "Akina, Kihei", "entry_status": "confirmed"},
        {"player_id": "99999", "player_name": "Finau, Tony", "entry_status": "confirmed"},
    ]
    resolved, audit = resolve_field_identities(
        field_rows,
        players_rows,
        aliases_path=Path("config/player_aliases.csv"),
        source_id_namespace="pga_tour",
    )
    statuses = [item.match_status for item in resolved]
    ids = [item.player_id for item in resolved]
    assert audit["ok"] is True
    assert statuses.count("matched") + statuses.count("matched_no_prior_rounds") == 2
    assert set(ids) == {"c1", "c2"}


def test_identity_blocks_fully_unmatched_field(tmp_path, monkeypatch):
    """Regression: a 100% unmatched field fails closed, not silent admission."""
    from golf_props.events.event_control import EventControl

    paths = prepare_paths(tmp_path)
    ec = EventControl(
        event_key=KEY,
        event_name="Test Invitational",
        season=2025,
        state=wf.STATE_FORECAST_READY,
        first_tee_at_utc="2025-05-01T13:00:00Z",
        forecast_due_at_utc="2025-05-01T01:00:00Z",
    )
    ec.save(paths.event_control_path(KEY))
    paths.field_raw_path(KEY).parent.mkdir(parents=True, exist_ok=True)
    paths.field_raw_path(KEY).write_text(
        "player_id,player_name,entry_status\n"
        "1,\"Unknown, Person\",confirmed\n",
        encoding="utf-8",
    )
    notify_calls: list[str] = []
    monkeypatch.setattr(wf, "_notify_ops", lambda message: notify_calls.append(message))

    ok = wf._apply_identity(paths, ec, wf.utc_now(), [])

    assert ok is False
    assert ec.state == wf.STATE_BLOCKED
    audit = json.loads(paths.identity_audit_path(KEY).read_text())
    assert audit["problems"] == ["entire field unmatched (1 players)"]
