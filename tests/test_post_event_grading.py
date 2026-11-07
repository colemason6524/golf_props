"""Tests for the automatic post-event grading safeguard."""

import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError

import pytest

from golf_props.backtest.forecast_archive import REQUIRED_ARCHIVE_FILES
from golf_props.events.event_control import STATE_FORECAST_ARCHIVED, EventControl
from golf_props.ingestion import cbs_results
from golf_props.notifications import grade_recap as gr
from golf_props.pipelines import post_event_grading as peg
from golf_props.pipelines import weekly_forecast as wf

KEY = "test_event_2026"
END_DATE = "2026-03-08"
NOW = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
ACTIVATION = "2026-01-01T00:00:00Z"


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


def _rows_html(rows) -> str:
    header = (
        "<table><thead><tr><th></th><th>pos</th><th>ctry</th><th>name</th>"
        "<th>to par</th><th>earnings</th><th>r1</th><th>r2</th><th>r3</th>"
        "<th>r4</th><th>total</th></tr></thead><tbody>"
    )
    rendered_rows = []
    for position, name in rows:
        cells = ["", position, "", name, "E", "$1", "70", "70", "70", "70", "280"]
        rendered = []
        for index, value in enumerate(cells):
            if index == 3:
                rendered.append(
                    '<td><span class="CellPlayerName--long"><a>' + str(value) + "</a></span></td>"
                )
            else:
                rendered.append(f"<td>{value}</td>")
        rendered_rows.append(
            '<tr class="TableBase-bodyTr GolfLeaderboard-bodyTr">'
            + "".join(rendered)
            + "</tr>"
        )
    return header + "".join(rendered_rows) + "</tbody></table>"


def _results_page(path: Path, third_name: str = "Gamma Three") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _rows_html([("1", "Alpha One"), ("T2", "Beta Two"), ("WD", third_name)]),
        encoding="utf-8",
    )
    return path


def _live_results_page(path: Path) -> Path:
    """A live leaderboard layout: thru/today header and 12-cell rows."""
    header = (
        "<table><thead><tr><th></th><th>pos</th><th>ctry</th><th>name</th>"
        "<th>to par</th><th>thru</th><th>today</th><th>r1</th><th>r2</th>"
        "<th>r3</th><th>r4</th><th>total</th></tr></thead><tbody>"
    )
    rows = []
    for position, name in (("1", "Alpha One"), ("T2", "Beta Two")):
        rows.append(
            '<tr class="TableBase-bodyTr GolfLeaderboard-bodyTr"><td></td>'
            f"<td>{position}</td><td></td>"
            '<td><span class="CellPlayerName--long"><a>' + name + "</a></span></td>"
            "<td>-9</td><td>3*</td><td>E</td><td>68</td><td>67</td><td>65</td>"
            "<td>-</td><td>200</td></tr>"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "".join(rows) + "</tbody></table>", encoding="utf-8")
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


def _prepare(
    tmp_path, monkeypatch, end_date=END_DATE, activation: Optional[str] = ACTIVATION
):
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
    monkeypatch.setattr(peg, "DELIVERY_ROOT", tmp_path / "delivery")
    monkeypatch.setattr(peg, "ODDS_ARCHIVE_ROOT", tmp_path / "odds")
    monkeypatch.delenv("GOLF_PROPS_DISCORD_WEBHOOK_URL", raising=False)
    if activation is None:
        monkeypatch.delenv("GOLF_PROPS_RECAP_ACTIVATION_UTC", raising=False)
    else:
        monkeypatch.setenv("GOLF_PROPS_RECAP_ACTIVATION_UTC", activation)
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


def _receipt(tmp_path) -> dict:
    path = tmp_path / "delivery" / KEY / "grade_recap_receipt.json"
    return json.loads(path.read_text(encoding="utf-8"))


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


@pytest.fixture
def webhook_transport(monkeypatch):
    calls = []

    def transport(payload, url):
        calls.append((payload, url))
        return {
            "status_code": 204,
            "message_id": "msg-123",
            "ambiguous": False,
            "error": "",
        }

    monkeypatch.setattr(peg, "RECAP_TRANSPORT_OVERRIDE", transport)
    monkeypatch.setenv("GOLF_PROPS_DISCORD_WEBHOOK_URL", "https://example.invalid/webhook")
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
    assert record["event_finality"]["state"] == "final"
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
    (output / "grading_manifest.json").write_text("{}\n", encoding="utf-8")
    (output / "metrics.csv").write_text("target\n", encoding="utf-8")

    summary = peg.attempt_post_event_grading(paths, NOW)

    assert [item["event_key"] for item in summary["graded"]] == [KEY]
    record = json.loads(
        (paths.weekly_dir / KEY / "grading.json").read_text(encoding="utf-8")
    )
    assert record["reused_existing_output"] is True
    assert spy["notify"] == []
    assert spy["dashboard"][0][0] == "observing"
    # The adopted grade cannot be previewed (no real metrics), but the loop
    # must record the recap error instead of raising or crashing.
    assert summary["recap"][0]["status"] == "error"


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
    # Discord gets a clean line; raw exception text stays in the record.
    assert spy["notify"][0] == (
        "golf post-event grading for Test Event could not finish yet; "
        "will retry next run"
    )
    for leaked in ("ForecastGradingError", "Traceback"):
        assert leaked not in spy["notify"][0]
    assert spy["dashboard"] == [
        ("blocked", f"[URGENT] {spy['notify'][0]}")
    ]


def test_results_not_published_yet_stay_pending_without_alert(tmp_path, monkeypatch, spy):
    paths = _prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(
        cbs_results, "collect_cbs_results", lambda *a, **k: {"events": []}
    )

    summary = peg.attempt_post_event_grading(paths, NOW)

    assert summary["failed"] == []
    assert [item["event_key"] for item in summary["pending"]] == [KEY]
    record = json.loads(
        (paths.weekly_dir / KEY / "grading.json").read_text(encoding="utf-8")
    )
    assert record["status"] == "pending"
    assert "no completed events" in record["reason"]
    assert record["alerted"] is True  # a new state, but never alerted as URGENT
    assert spy["notify"] == [] and spy["dashboard"] == []
    attempts = (paths.weekly_dir / KEY / "grading_attempts.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(attempts) == 1
    assert json.loads(attempts[0])["status"] == "pending"


def test_genuine_fetch_failure_still_records_and_alerts(tmp_path, monkeypatch, spy):
    paths = _prepare(tmp_path, monkeypatch)

    def boom(*args, **kwargs):
        raise HTTPError("https://example.invalid/schedule?token=secret", 500, "boom", {}, None)

    monkeypatch.setattr(cbs_results, "collect_cbs_results", boom)

    summary = peg.attempt_post_event_grading(paths, NOW)

    assert [item["event_key"] for item in summary["failed"]] == [KEY]
    record = json.loads(
        (paths.weekly_dir / KEY / "grading.json").read_text(encoding="utf-8")
    )
    assert record["status"] == "failed"
    assert "HTTP 500" in record["reason"]
    assert len(spy["notify"]) == 1
    assert spy["dashboard"][0][0] == "blocked"
    # No secret query string may survive in the append-only diagnosis.
    attempts = (paths.weekly_dir / KEY / "grading_attempts.jsonl").read_text(
        encoding="utf-8"
    )
    assert "token=secret" not in attempts


def test_live_leaderboard_is_in_progress_and_silent(tmp_path, monkeypatch, spy):
    paths = _prepare(tmp_path, monkeypatch)
    results_dir = tmp_path / "results" / KEY
    _live_results_page(results_dir / "cbs_final_leaderboard.html")

    summary = peg.attempt_post_event_grading(paths, NOW)

    assert summary["failed"] == [] and summary["pending"] == []
    assert [item["event_key"] for item in summary["in_progress"]] == [KEY]
    record = json.loads(
        (paths.weekly_dir / KEY / "grading.json").read_text(encoding="utf-8")
    )
    assert record["status"] == "in_progress"
    assert record["context"]["finality"]["reason"] == "live_header_columns"
    assert spy["notify"] == [] and spy["dashboard"] == []
    assert not (tmp_path / "grading" / KEY).exists()


def test_unknown_finality_stays_pending_not_failed(tmp_path, monkeypatch, spy):
    """An unprovable page (earnings placeholders only) waits instead of grading."""
    paths = _prepare(tmp_path, monkeypatch)
    results_dir = tmp_path / "results" / KEY
    results_dir.mkdir(parents=True)
    (results_dir / "cbs_final_leaderboard.html").write_text(
        "<table><thead><tr><th></th><th>pos</th><th>ctry</th><th>name</th>"
        "<th>to par</th><th>earnings</th><th>r1</th><th>r2</th>"
        "<th>r3</th><th>r4</th><th>total</th></tr></thead><tbody>"
        '<tr class="TableBase-bodyTr GolfLeaderboard-bodyTr"><td></td><td>1</td><td></td>'
        '<td><span class="CellPlayerName--long"><a>Alpha One</a></span></td>'
        "<td>-6</td><td>-</td><td>70</td><td>70</td><td>-</td><td>-</td><td>140</td></tr>"
        "</tbody></table>",
        encoding="utf-8",
    )

    summary = peg.attempt_post_event_grading(paths, NOW)

    assert summary["failed"] == []
    assert [item["event_key"] for item in summary["pending"]] == [KEY]
    record = json.loads(
        (paths.weekly_dir / KEY / "grading.json").read_text(encoding="utf-8")
    )
    assert record["status"] == "pending"
    assert "finality not provable" in record["reason"]
    assert spy["notify"] == [] and spy["dashboard"] == []


def test_tie_for_first_is_manual_review_not_a_grade(tmp_path, monkeypatch, spy):
    paths = _prepare(tmp_path, monkeypatch)
    results_dir = tmp_path / "results" / KEY
    results_dir.mkdir(parents=True)
    (results_dir / "cbs_final_leaderboard.html").write_text(
        _rows_html(
            [
                ("T1", "Alpha One"),
                ("T1", "Beta Two"),
                ("WD", "Gamma Three"),
            ]
        ),
        encoding="utf-8",
    )

    summary = peg.attempt_post_event_grading(paths, NOW)

    assert summary["graded"] == [] and summary["failed"] == []
    assert [item["event_key"] for item in summary["manual_review"]] == [KEY]
    record = json.loads(
        (paths.weekly_dir / KEY / "grading.json").read_text(encoding="utf-8")
    )
    assert record["status"] == "manual_review"
    assert record["context"]["winner_row_count"] == 2
    assert not (tmp_path / "grading" / KEY).exists()
    assert len(spy["notify"]) == 1
    assert "manual review" in spy["notify"][0]
    assert "Alpha One" not in spy["notify"][0]


def test_pending_then_final_emits_one_recap_outbox(tmp_path, monkeypatch, spy):
    paths = _prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(
        cbs_results, "collect_cbs_results", lambda *a, **k: {"events": []}
    )
    first = peg.attempt_post_event_grading(paths, NOW)
    assert [item["event_key"] for item in first["pending"]] == [KEY]
    assert not (tmp_path / "delivery" / KEY / "grade_recap_receipt.json").exists()

    # Results arrive; the same event now grades and leaves exactly one outbox.
    _preserve_results(tmp_path)
    second = peg.attempt_post_event_grading(paths, NOW + timedelta(hours=2))

    assert [item["event_key"] for item in second["graded"]] == [KEY]
    assert second["recap"][0]["status"] == "not_configured"
    receipt_path = tmp_path / "delivery" / KEY / "grade_recap_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "pending"
    assert receipt["attempts"] == 0
    assert "webhook not configured" in receipt["notes"]

    # Another run must not duplicate the outbox or fabricate a delivered state.
    third = peg.attempt_post_event_grading(paths, NOW + timedelta(hours=4))
    assert third["skipped"] == [{"event_key": KEY, "reason": "already_graded"}]
    again = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert again["status"] == "pending" and again["attempts"] == 0


def test_already_graded_with_pending_receipt_still_sends(
    tmp_path, monkeypatch, spy, webhook_transport
):
    paths = _prepare(tmp_path, monkeypatch)
    _preserve_results(tmp_path)
    monkeypatch.setattr(
        peg, "RECAP_TRANSPORT_OVERRIDE", None
    )  # first pass: no transport, receipt stays pending
    monkeypatch.delenv("GOLF_PROPS_DISCORD_WEBHOOK_URL", raising=False)
    first = peg.attempt_post_event_grading(paths, NOW)
    assert first["recap"][0]["status"] == "not_configured"

    # Restore a working transport; the grade is already_graded but the recap
    # was never delivered, so it must still be sent exactly once.
    monkeypatch.setattr(
        peg,
        "RECAP_TRANSPORT_OVERRIDE",
        lambda payload, url: (
            webhook_transport.append((payload, url))
            or {"status_code": 204, "message_id": "msg-1", "ambiguous": False, "error": ""}
        ),
    )
    monkeypatch.setenv("GOLF_PROPS_DISCORD_WEBHOOK_URL", "https://example.invalid/webhook")

    second = peg.attempt_post_event_grading(paths, NOW + timedelta(hours=2))

    assert second["skipped"] == [{"event_key": KEY, "reason": "already_graded"}]
    assert second["recap"][0]["status"] == "sent"
    receipt = _receipt(tmp_path)
    assert receipt["status"] == "sent"
    assert receipt["message_id"] == "msg-1"
    assert len(webhook_transport) == 1

    third = peg.attempt_post_event_grading(paths, NOW + timedelta(hours=4))
    assert third["recap"][0]["status"] == "already_sent"
    assert len(webhook_transport) == 1


def test_legacy_grade_is_held_without_activation(tmp_path, monkeypatch, spy):
    paths = _prepare(tmp_path, monkeypatch, activation=None)
    _preserve_results(tmp_path)

    summary = peg.attempt_post_event_grading(paths, NOW)

    assert [item["event_key"] for item in summary["graded"]] == [KEY]
    assert summary["recap"][0]["status"] == "legacy_backfill_pending"
    receipt = _receipt(tmp_path)
    assert receipt["status"] == "legacy_backfill_pending"
    assert receipt["attempts"] == 0


def test_uninitialized_durable_state_holds_a_new_grade(tmp_path, monkeypatch, spy):
    paths = _prepare(tmp_path, monkeypatch, activation=None)
    _preserve_results(tmp_path)

    summary = peg.attempt_post_event_grading(paths, NOW)

    assert summary["recap"][0]["status"] == "legacy_backfill_pending"
    receipt = _receipt(tmp_path)
    assert receipt["activation"]["source"] == "uninitialized"
    assert receipt["attempts"] == 0


def test_durable_activation_admits_a_future_grade_on_the_existing_timer(
    tmp_path, monkeypatch, spy, webhook_transport
):
    paths = _prepare(tmp_path, monkeypatch, activation=None)
    monkeypatch.setenv("GOLF_PROPS_DISCORD_WEBHOOK_URL", "https://example.invalid/webhook")
    gr.initialize_activation_state(
        gr.activation_state_path(paths.weekly_dir),
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    _preserve_results(tmp_path)

    summary = peg.attempt_post_event_grading(paths, NOW)

    assert summary["recap"][0]["status"] == "sent"
    receipt = _receipt(tmp_path)
    assert receipt["status"] == "sent"
    assert receipt["activation"]["source"] == "durable_state"
    assert len(webhook_transport) == 1

    # The next two-hourly tick dedupes rather than sending twice.
    again = peg.attempt_post_event_grading(paths, NOW + timedelta(hours=2))
    assert again["recap"][0]["status"] == "already_sent"
    assert len(webhook_transport) == 1


def test_durable_activation_holds_a_grade_recorded_before_it(
    tmp_path, monkeypatch, spy
):
    paths = _prepare(tmp_path, monkeypatch, activation=None)
    gr.initialize_activation_state(
        gr.activation_state_path(paths.weekly_dir),
        now=NOW + timedelta(days=1),
    )
    _preserve_results(tmp_path)

    summary = peg.attempt_post_event_grading(paths, NOW)

    assert summary["recap"][0]["status"] == "legacy_backfill_pending"
    assert _receipt(tmp_path)["attempts"] == 0


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


def test_repeat_fetch_failure_is_retried_but_alerted_once(tmp_path, monkeypatch, spy):
    paths = _prepare(tmp_path, monkeypatch)

    def boom(*args, **kwargs):
        raise HTTPError("https://example.invalid/x", 503, "unavailable", {}, None)

    monkeypatch.setattr(cbs_results, "collect_cbs_results", boom)

    peg.attempt_post_event_grading(paths, NOW)
    peg.attempt_post_event_grading(paths, NOW + timedelta(hours=2))

    assert len(spy["notify"]) == 1
    assert len(spy["dashboard"]) == 1
    record = json.loads(
        (paths.weekly_dir / KEY / "grading.json").read_text(encoding="utf-8")
    )
    assert record["status"] == "failed"
    assert record["alerted"] is False
    attempts = (paths.weekly_dir / KEY / "grading_attempts.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(attempts) == 2


def test_success_after_failure_keeps_the_failure_in_the_attempt_log(
    tmp_path, monkeypatch, spy
):
    paths = _prepare(tmp_path, monkeypatch)

    def boom(*args, **kwargs):
        raise HTTPError("https://example.invalid/x", 500, "boom", None, None)

    monkeypatch.setattr(cbs_results, "collect_cbs_results", boom)
    peg.attempt_post_event_grading(paths, NOW)

    # Results arrive: the preserved page is reused, so the collector is not
    # called again and the earlier failure stays in the attempt log.
    _preserve_results(tmp_path)
    second = peg.attempt_post_event_grading(paths, NOW + timedelta(hours=2))

    assert [item["event_key"] for item in second["graded"]] == [KEY]
    attempts = [
        json.loads(line)
        for line in (paths.weekly_dir / KEY / "grading_attempts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [entry["status"] for entry in attempts] == ["failed", "success"]
    assert "HTTP 500" in attempts[0]["reason"]


def test_recap_is_not_sent_when_the_grade_record_has_no_results_page(
    tmp_path, monkeypatch, spy
):
    """A graded artifact alone never proves which event page it came from."""
    paths = _prepare(tmp_path, monkeypatch)
    _preserve_results(tmp_path)
    monkeypatch.setattr(peg, "RECAP_TRANSPORT_OVERRIDE", None)
    monkeypatch.delenv("GOLF_PROPS_DISCORD_WEBHOOK_URL", raising=False)

    first = peg.attempt_post_event_grading(paths, NOW)
    assert first["recap"][0]["status"] == "not_configured"

    record_path = paths.weekly_dir / KEY / "grading.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["results_page"] = ""
    record_path.write_text(json.dumps(record), encoding="utf-8")

    calls = []
    monkeypatch.setattr(
        peg,
        "RECAP_TRANSPORT_OVERRIDE",
        lambda payload, url: calls.append(url)
        or {"status_code": 204, "message_id": "m", "ambiguous": False, "error": ""},
    )
    monkeypatch.setenv("GOLF_PROPS_DISCORD_WEBHOOK_URL", "https://example.invalid/webhook")

    second = peg.attempt_post_event_grading(paths, NOW + timedelta(hours=2))

    assert second["recap"][0]["status"] == "error"
    assert "results page" in second["recap"][0]["reason"]
    assert calls == []
    receipt = _receipt(tmp_path)
    assert receipt["status"] == "pending"  # untouched, never marked sent

