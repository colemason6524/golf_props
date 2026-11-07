"""End-to-end CLI regression: the recap must bind to the graded results page.

Reproduces the live failure ``publish-grade-recap --demo --allow-prior-grades``
showing an event window of 2026-01-08..2026-01-11, finality ``unknown`` and
winner ``not recorded`` for the graded Butterfield Bermuda Championship.

The live event directory preserves the whole 2026 season of CBS captures; the
pre-fix selector took ``sorted(glob("*.html"))[0]`` (the January Sentry page)
because no filename contains the word "leaderboard".  These tests use the real
captured pages, the real production-shaped directory layout and the real grading
manifest, and assert the page is selected by the manifest's results-page sha256.
"""

import json
import shutil
from pathlib import Path

import pytest

from golf_props import cli
from golf_props.notifications import grade_recap as gr

FIXTURES = Path(__file__).parent / "fixtures"
LIVE_RESULTS = FIXTURES / "golf_recap_live_results"
GRADE_DIR = FIXTURES / "bermuda_grade"
BERMUDA_PAGE = LIVE_RESULTS / "31000146_butterfield-bermuda-championship.html"
SENTRY_PAGE = LIVE_RESULTS / "31000071_the-sentry.html"
EVENT_KEY = "butterfield_bermuda_championship_2026"
EVENT_NAME = "Butterfield Bermuda Championship"
PAGE_SHA = "e216d82a38ec0d77e14b374d79688f7cafe019af552840582134671b79211bfe"
SENTRY_SHA = "8a51893619f6bd33d20af9cfeee8f64db99d36b83d6b7269e9fbb43723fc5b72"
# The observed live fingerprint of the wrong-page preview (regression evidence).
BAD_FINGERPRINT = "58ee3422c5431992a740c89ed1c06cdd5207548be8b8f192ab22a75d600ed84a"
EVENT_CONTROL = {
    "event_key": EVENT_KEY,
    "event_name": EVENT_NAME,
    "state": "forecast_archived",
    "competitive_start_date": "2026-10-22",
    "schedule_start_date": "2026-10-21",
    "schedule_end_date": "2026-10-24",
    "created_at_utc": "2026-10-07T12:17:00Z",
    "updated_at_utc": "2026-10-21T06:17:00Z",
}


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _project(tmp_path, monkeypatch, *, pages, tamper=()):
    """A production-shaped project root: season results, grade, control, delivery."""
    root = tmp_path / "project"
    results_dir = root / "data/raw/prospective_results" / EVENT_KEY
    results_dir.mkdir(parents=True)
    for source in pages:
        shutil.copy2(LIVE_RESULTS / source, results_dir / source)
    for name in tamper:
        target = results_dir / name
        target.write_text(target.read_text(encoding="utf-8") + "\n<!-- tampered -->\n", encoding="utf-8")
    grading_dir = root / "data/interim/reports/forecast_grading" / EVENT_KEY
    shutil.copytree(GRADE_DIR, grading_dir)
    weekly_dir = root / "data/interim/weekly" / EVENT_KEY
    weekly_dir.mkdir(parents=True)
    (weekly_dir / "event_control.json").write_text(
        json.dumps(EVENT_CONTROL), encoding="utf-8"
    )
    delivery_dir = root / "data/interim/reports/forecast_delivery" / EVENT_KEY
    delivery_dir.mkdir(parents=True)
    monkeypatch.setattr(cli, "PROJECT_ROOT", root)
    monkeypatch.delenv("GOLF_PROPS_DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv(gr.ACTIVATION_ENV, raising=False)
    return root, weekly_dir, delivery_dir


def _dry_run(capsys):
    code = cli.main(
        [
            "publish-grade-recap",
            "--event-key",
            EVENT_KEY,
            "--demo",
            "--allow-prior-grades",
        ]
    )
    return code, capsys.readouterr()


def _send(capsys, weekly_dir, monkeypatch):
    calls = []

    def fake_transport(payload, url):
        calls.append((payload, url))
        return {"status_code": 204, "message_id": "msg-1", "ambiguous": False, "error": ""}

    monkeypatch.setattr(gr, "default_transport", fake_transport)
    monkeypatch.setenv("GOLF_PROPS_DISCORD_WEBHOOK_URL", "https://example.invalid/webhook")
    code = cli.main(
        [
            "publish-grade-recap",
            "--event-key",
            EVENT_KEY,
            "--demo",
            "--allow-prior-grades",
            "--send",
            "--weekly-dir",
            str(weekly_dir),
        ]
    )
    return code, capsys.readouterr(), calls


def test_fixtures_are_the_real_graded_bytes():
    assert _sha(BERMUDA_PAGE) == PAGE_SHA
    assert _sha(SENTRY_PAGE) == SENTRY_SHA
    manifest = json.loads((GRADE_DIR / "grading_manifest.json").read_text(encoding="utf-8"))
    assert manifest["input_sha256"]["results_page"] == PAGE_SHA
    assert manifest["results_source"]["url"].endswith("/31000146/butterfield-bermuda-championship/")


def test_cli_dry_run_uses_the_graded_october_page_not_the_january_neighbour(
    tmp_path, monkeypatch, capsys
):
    _project(tmp_path, monkeypatch, pages=(SENTRY_PAGE.name, BERMUDA_PAGE.name))

    code, out = _dry_run(capsys)

    assert code == 0
    assert "grade_recap_event_window=2026-10-22..2026-10-25 (source=results_page)" in out.out
    assert "grade_recap_event_finality=final (earnings_column_settled)" in out.out
    assert "grade_recap_winner=Austin Smotherman" in out.out
    assert "grade_recap_graded_players=117" in out.out
    assert "grade_recap_priced_roi=unavailable" in out.out
    assert "grade_recap_results_page_verified=true" in out.out
    assert "grade_recap_release_blockers=none" in out.out
    assert "grade_recap_delivery_state=not_sent" in out.out
    assert "2026-01-08" not in out.out
    assert BAD_FINGERPRINT not in out.out

    preview_json = Path(out.out.split("grade_recap_preview_json=")[1].splitlines()[0])
    payload = json.loads(preview_json.read_text(encoding="utf-8"))
    recap = payload["recap"]
    assert recap["event_dates"] == {
        "start": "2026-10-22",
        "end": "2026-10-25",
        "source": "results_page",
    }
    assert recap["winner"] == "Austin Smotherman" and recap["winner_rows"] == 1
    assert recap["event_finality"]["state"] == "final"
    assert recap["coverage"]["forecast_players"] == 120
    assert recap["coverage"]["intersection_players"] == 118
    assert recap["coverage"]["graded_players"] == 117
    assert recap["results_evidence"]["verified"] is True
    assert recap["results_evidence"]["sha256"] == PAGE_SHA
    assert recap["results_evidence"]["path"].endswith(BERMUDA_PAGE.name)
    assert recap["date_evidence"]["check"]["consistent"] is True
    embed = payload["payload"]["embeds"][0]
    assert embed["description"] == (
        "2026-10-22..2026-10-25 | final | winner Austin Smotherman"
    )
    assert embed["title"].endswith("| Final Grade")
    assert all(field["name"] != "Status" for field in embed["fields"])
    assert "Priced ROI unavailable" in json.dumps(payload)
    assert "2026-01-08" not in json.dumps(payload)

    markdown = Path(out.out.split("grade_recap_preview_markdown=")[1].splitlines()[0])
    text = markdown.read_text(encoding="utf-8")
    assert "2026-10-22..2026-10-25" in text and "Austin Smotherman" in text
    assert "117 of 120" in text
    assert "2026-01-08" not in text


def test_cli_send_posts_only_the_validated_october_payload(
    tmp_path, monkeypatch, capsys
):
    _project(tmp_path, monkeypatch, pages=(SENTRY_PAGE.name, BERMUDA_PAGE.name))
    code, dry = _dry_run(capsys)
    assert code == 0
    preview_json = Path(dry.out.split("grade_recap_preview_json=")[1].splitlines()[0])
    preview = json.loads(preview_json.read_text(encoding="utf-8"))

    code, out, calls = _send(capsys, tmp_path / "project/data/interim/weekly" / EVENT_KEY, monkeypatch)

    assert code == 0
    assert "grade_recap_status=sent" in out.out
    assert "grade_recap_message_id=msg-1" in out.out
    assert len(calls) == 1
    payload, url = calls[0]
    assert url == "https://example.invalid/webhook"
    # Exactly the payload the dry run validated.
    assert json.dumps(payload, sort_keys=True) == json.dumps(
        preview["payload"], sort_keys=True
    )
    embed = payload["embeds"][0]
    assert embed["description"] == (
        "2026-10-22..2026-10-25 | final | winner Austin Smotherman"
    )
    assert "2026-01-08" not in json.dumps(payload)
    receipt = json.loads(
        (tmp_path / "project/data/interim/reports/forecast_delivery" / EVENT_KEY / gr.RECEIPT_NAME)
        .read_text(encoding="utf-8")
    )
    assert receipt["status"] == "sent"
    assert receipt["event_finality"] == "final"
    assert receipt["grade_fingerprint"] == preview["recap"]["fingerprint"]


def test_cli_without_the_graded_page_previews_pending_and_refuses_to_send(
    tmp_path, monkeypatch, capsys
):
    # Only the unrelated January page is preserved: no page matches the grade hash.
    _project(tmp_path, monkeypatch, pages=(SENTRY_PAGE.name,))

    code, out = _dry_run(capsys)
    assert code == 0  # a pending preview is allowed ...
    assert "grade_recap_results_page_verified=false" in out.out
    assert "no preserved page matches the graded results page sha256" in out.out
    assert "grade_recap_event_finality=unknown" in out.out
    assert "grade_recap_winner=not recorded" in out.out
    assert "grade_recap_release_blockers=" in out.out and "none" not in out.out.split(
        "grade_recap_release_blockers="
    )[1].splitlines()[0]
    assert "grade_recap_delivery_state=blocked_pending" in out.out
    assert "2026-01-08" not in out.out  # never republishes the neighbour's dates

    # ... but --send must fail closed even with --demo --allow-prior-grades.
    code, out, calls = _send(capsys, tmp_path / "project/data/interim/weekly" / EVENT_KEY, monkeypatch)
    assert code == 1
    assert calls == []
    assert "grade recap delivery failed" in out.err
    receipt = (
        tmp_path / "project/data/interim/reports/forecast_delivery" / EVENT_KEY / gr.RECEIPT_NAME
    )
    assert not receipt.exists()


def test_cli_refuses_a_page_whose_bytes_do_not_match_the_grade(
    tmp_path, monkeypatch, capsys
):
    _project(
        tmp_path,
        monkeypatch,
        pages=(SENTRY_PAGE.name, BERMUDA_PAGE.name),
        tamper=(BERMUDA_PAGE.name,),
    )

    code, out = _dry_run(capsys)
    assert code == 0
    assert "grade_recap_results_page_verified=false" in out.out
    assert "no preserved page matches the graded results page sha256" in out.out

    code, out, calls = _send(capsys, tmp_path / "project/data/interim/weekly" / EVENT_KEY, monkeypatch)
    assert code == 1 and calls == []


def test_cli_refuses_ambiguous_results_page_copies(tmp_path, monkeypatch, capsys):
    root, weekly_dir, _ = _project(
        tmp_path, monkeypatch, pages=(SENTRY_PAGE.name, BERMUDA_PAGE.name)
    )
    results_dir = root / "data/raw/prospective_results" / EVENT_KEY
    shutil.copy2(results_dir / BERMUDA_PAGE.name, results_dir / "31000146_bermuda-copy.html")

    code, out = _dry_run(capsys)
    assert code == 0
    assert "ambiguous results page: 2 preserved files share the graded results hash" in out.out

    code, out, calls = _send(capsys, weekly_dir, monkeypatch)
    assert code == 1 and calls == []


def test_cli_explicit_results_page_is_hash_checked(tmp_path, monkeypatch, capsys):
    _project(tmp_path, monkeypatch, pages=(SENTRY_PAGE.name, BERMUDA_PAGE.name))

    code = cli.main(
        [
            "publish-grade-recap",
            "--event-key",
            EVENT_KEY,
            "--results-page",
            str(SENTRY_PAGE),
            "--demo",
            "--allow-prior-grades",
        ]
    )
    out = capsys.readouterr()
    assert code == 0
    assert "grade_recap_results_page_verified=false" in out.out
    assert "grade_recap_event_finality=unknown" in out.out
    assert "grade_recap_release_blockers=" in out.out
