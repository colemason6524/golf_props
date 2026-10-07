"""Tests for the automatic post-event grading safeguard."""

import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from golf_props.backtest.forecast_archive import REQUIRED_ARCHIVE_FILES
from golf_props.events.event_control import STATE_FORECAST_ARCHIVED, EventControl
from golf_props.ingestion import cbs_results
from golf_props.pipelines import post_event_grading as peg
from golf_props.pipelines import weekly_forecast as wf

KEY = "test_event_2026"
END_DATE = "2026-03-08"
NOW = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _archive(archive: Path) -> Path:
    archive.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_ARCHIVE_FILES:
        if name != "archive_manifest.json":
            (archive / name).write_text(name, encoding="utf-8")
    with (archive / "predictions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "event_name",
                "event_date",
                "player_id",
                "player_name",
                "top20_prob",
                "top10_prob",
                "top5_prob",
                "winner_prob",
            ],
        )
        writer.writeheader()
        writer.writerows(
            [
                {"event_name": "Test Event", "event_date": "2026-03-05", "player_id": "p1", "player_name": "Alpha One", "top20_prob": .9, "top10_prob": .7, "top5_prob": .5, "winner_prob": .3},
                {"event_name": "Test Event", "event_date": "2026-03-05", "player_id": "p2", "player_name": "Beta Two", "top20_prob": .8, "top10_prob": .5, "top5_prob": .3, "winner_prob": .2},
                {"event_name": "Test Event", "event_date": "2026-03-05", "player_id": "p3", "player_name": "Gamma Three", "top20_prob": .7, "top10_prob": .3, "top5_prob": .1, "winner_prob": .1},
            ]
        )
    (archive / "run_manifest.json").write_text(
        json.dumps({"eligibility": {"classification": "prospective_forecast"}}),
        encoding="utf-8",
    )
    hashes = {
        path.name: _sha(path)
        for path in archive.iterdir()
        if path.name != "archive_manifest.json"
    }
    (archive / "archive_manifest.json").write_text(
        json.dumps({"schema_version": 1, "files": hashes}), encoding="utf-8"
    )
    return archive


def _results_page(path: Path, third_name: str = "Gamma Three") -> Path:
    rows = []
    for position, name in [("1", "Alpha One"), ("T2", "Beta Two"), ("WD", third_name)]:
        cells = ["", position, "", name, "E", "$1", "70", "70", "70", "70", "280"]
        rendered = []
        for index, value in enumerate(cells):
            if index == 3:
                rendered.append(
                    '<td><span class="CellPlayerName--long"><a>' + name + "</a></span></td>"
                )
            else:
                rendered.append(f"<td>{value}</td>")
        rows.append(
            '<tr class="TableBase-bodyTr GolfLeaderboard-bodyTr">'
            + "".join(rendered)
            + "</tr>"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(rows), encoding="utf-8")
    return path


def _rolling_metrics(path: Path) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["target", "model_brier", "model_log_loss"]
        )
        writer.writeheader()
        for target in ("top20", "top10", "top5", "winner"):
            writer.writerow({"target": target, "model_brier": .1, "model_log_loss": .2})
    return path


def _prepare(tmp_path, monkeypatch, end_date=END_DATE):
    """Build tmp paths, an archived event control record, and gradable inputs."""
    paths = wf.WeeklyPaths(
        weekly_dir=tmp_path / "weekly", archives_root=tmp_path / "archives"
    )
    ec = EventControl(
        event_key=KEY,
        event_name="Test Event",
        season=2026,
        schedule_start_date="2026-03-05",
        schedule_end_date=end_date,
        state=STATE_FORECAST_ARCHIVED,
        created_at_utc="2026-03-01T00:00:00Z",
        updated_at_utc="2026-03-05T00:00:00Z",
    )
    ec.save(paths.event_control_path(KEY))
    _archive(paths.archive_dir(KEY))

    monkeypatch.setattr(peg, "GRADING_ROOT", tmp_path / "grading")
    monkeypatch.setattr(peg, "PROSPECTIVE_RESULTS_ROOT", tmp_path / "results")
    rolling = _rolling_metrics(tmp_path / "rolling.csv")
    monkeypatch.setattr(peg, "_rolling_metrics_path", lambda: rolling)
    return paths


def _preserve_results(tmp_path, third_name="Gamma Three"):
    results_dir = tmp_path / "results" / KEY
    page = _results_page(results_dir / "cbs_final_leaderboard.html", third_name)
    (results_dir / "source_manifest.json").write_text(
        json.dumps(
            {
                "source": "cbs_sports",
                "event_name": "Test Event",
                "event_key": KEY,
                "leaderboard_url": "https://www.cbssports.com/golf/leaderboard/pga-tour/1/test-event/",
                "files": {"cbs_final_leaderboard.html": _sha(page)},
            }
        ),
        encoding="utf-8",
    )
    return page


@pytest.fixture
def spy(monkeypatch):
    calls = {"notify": [], "dashboard": []}
    monkeypatch.setattr(peg, "_notify_ops", lambda message: calls["notify"].append(message))
    monkeypatch.setattr(
        peg,
        "_dashboard_checkpoint",
        lambda status, summary, project=peg.DEFAULT_DASHBOARD_PROJECT: calls["dashboard"].append(
            (status, summary)
        ),
    )
    return calls


def test_success_path_grades_and_records(tmp_path, monkeypatch, spy):
    paths = _prepare(tmp_path, monkeypatch)
    page = _preserve_results(tmp_path)

    summary = peg.attempt_post_event_grading(paths, NOW)

    assert [item["event_key"] for item in summary["graded"]] == [KEY]
    assert summary["failed"] == []
    record = json.loads(
        (paths.weekly_dir / KEY / "grading.json").read_text(encoding="utf-8")
    )
    assert record["status"] == "success"
    assert record["reused_existing_output"] is False
    assert record["results_page"] == str(page)
    output = tmp_path / "grading" / KEY
    for name in ("graded_predictions.csv", "metrics.csv", "report.md", "grading_manifest.json"):
        assert (output / name).exists(), name
    assert spy["notify"] == []
    assert spy["dashboard"] == [
        ("observing", f"golf_props graded Test Event ({KEY})")
    ]


def test_existing_complete_grade_is_adopted(tmp_path, monkeypatch, spy):
    paths = _prepare(tmp_path, monkeypatch)
    output = tmp_path / "grading" / KEY
    output.mkdir(parents=True)
    (output / "grading_manifest.json").write_text("{}", encoding="utf-8")
    (output / "metrics.csv").write_text("target\n", encoding="utf-8")

    summary = peg.attempt_post_event_grading(paths, NOW)

    assert [item["event_key"] for item in summary["graded"]] == [KEY]
    record = json.loads(
        (paths.weekly_dir / KEY / "grading.json").read_text(encoding="utf-8")
    )
    assert record["reused_existing_output"] is True
    assert spy["notify"] == []
    assert spy["dashboard"][0][0] == "observing"


def test_grading_failure_records_and_alerts(tmp_path, monkeypatch, spy):
    paths = _prepare(tmp_path, monkeypatch)
    # Results with no player in common with the forecast -> grader raises.
    _preserve_results(tmp_path, third_name="Nobody One")
    page = tmp_path / "results" / KEY / "cbs_final_leaderboard.html"
    _results_page(page, third_name="Nobody One")
    page.write_text(
        page.read_text(encoding="utf-8")
        .replace("Alpha One", "Nobody One")
        .replace("Beta Two", "Nobody Two"),
        encoding="utf-8",
    )

    summary = peg.attempt_post_event_grading(paths, NOW)

    assert summary["graded"] == []
    assert [item["event_key"] for item in summary["failed"]] == [KEY]
    record = json.loads(
        (paths.weekly_dir / KEY / "grading.json").read_text(encoding="utf-8")
    )
    assert record["status"] == "failed"
    assert "ForecastGradingError" in record["reason"]
    assert len(spy["notify"]) == 1
    assert "grading failed for Test Event" in spy["notify"][0]
    assert spy["dashboard"] == [
        ("blocked", f"[URGENT] {spy['notify'][0]}")
    ]


def test_results_unavailable_records_and_alerts(tmp_path, monkeypatch, spy):
    paths = _prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(
        cbs_results, "collect_cbs_results", lambda *a, **k: {"events": []}
    )

    summary = peg.attempt_post_event_grading(paths, NOW)

    assert [item["event_key"] for item in summary["failed"]] == [KEY]
    record = json.loads(
        (paths.weekly_dir / KEY / "grading.json").read_text(encoding="utf-8")
    )
    assert record["status"] == "failed"
    assert "no preserved CBS results" in record["reason"]
    assert len(spy["notify"]) == 1
    assert spy["dashboard"][0][0] == "blocked"
    assert spy["dashboard"][0][1].startswith("[URGENT]")


def test_idempotent_skips_already_graded(tmp_path, monkeypatch, spy):
    paths = _prepare(tmp_path, monkeypatch)
    record_path = paths.weekly_dir / KEY / "grading.json"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(
        json.dumps({"status": "success", "event_key": KEY}), encoding="utf-8"
    )
    monkeypatch.setattr(
        peg, "grade_forecast", lambda *a, **k: pytest.fail("must not re-grade")
    )

    summary = peg.attempt_post_event_grading(paths, NOW)

    assert summary["graded"] == []
    assert summary["failed"] == []
    assert summary["skipped"] == [{"event_key": KEY, "reason": "already_graded"}]
    assert spy["notify"] == [] and spy["dashboard"] == []


def test_pre_end_date_is_noop(tmp_path, monkeypatch, spy):
    today = NOW.date().isoformat()
    paths = _prepare(tmp_path, monkeypatch, end_date=today)

    summary = peg.attempt_post_event_grading(paths, NOW)

    assert summary["skipped"] == [{"event_key": KEY, "reason": "tournament_not_finished"}]
    assert summary["graded"] == [] and summary["failed"] == []
    assert not (paths.weekly_dir / KEY / "grading.json").exists()
    assert spy["notify"] == [] and spy["dashboard"] == []


def test_grace_boundary_grades_the_day_after_end(tmp_path, monkeypatch, spy):
    end = (NOW.date() - timedelta(days=1)).isoformat()
    paths = _prepare(tmp_path, monkeypatch, end_date=end)
    _preserve_results(tmp_path)

    summary = peg.attempt_post_event_grading(paths, NOW)

    assert [item["event_key"] for item in summary["graded"]] == [KEY]


def test_repeat_failure_is_retried_but_alerted_once(tmp_path, monkeypatch, spy):
    paths = _prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(
        cbs_results, "collect_cbs_results", lambda *a, **k: {"events": []}
    )

    peg.attempt_post_event_grading(paths, NOW)
    peg.attempt_post_event_grading(paths, NOW + timedelta(hours=2))

    assert len(spy["notify"]) == 1
    assert len(spy["dashboard"]) == 1
    record = json.loads(
        (paths.weekly_dir / KEY / "grading.json").read_text(encoding="utf-8")
    )
    assert record["status"] == "failed"
    assert record["alerted"] is False
