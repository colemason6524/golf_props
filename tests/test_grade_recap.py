"""Tests for the final-grade recap: builder, preview, receipt and delivery."""

import json
import re
from pathlib import Path

import pytest

from golf_props.notifications import grade_recap as gr
from golf_props.notifications.discord import PROHIBITED_WORDS

FIXTURES = Path(__file__).parent / "fixtures"
GRADE_DIR = FIXTURES / "bermuda_grade"
RESULTS_PAGE = FIXTURES / "cbs_final_leaderboard_bermuda_excerpt.html"
EVENT_KEY = "butterfield_bermuda_championship_2026"
EVENT_NAME = "Butterfield Bermuda Championship"
ACTIVE = "2026-10-26T00:00:00Z"
NOW = gr._parse_iso("2026-10-27T02:17:00Z")


def _recap(tmp_path, *, odds_dir=None, finality=None, demo_label=None):
    return gr.build_recap(
        event_key=EVENT_KEY,
        event_name=EVENT_NAME,
        grading_dir=GRADE_DIR,
        results_page=RESULTS_PAGE,
        event_dates={"start": "2026-10-22", "end": "2026-10-25", "source": "test"},
        finality=finality or {"state": "final", "reason": "earnings_column_settled"},
        odds_archive_dir=odds_dir if odds_dir is not None else tmp_path / "no-odds",
        demo_label=demo_label,
    )


def _ok(message_id="msg-1"):
    return {
        "status_code": 204,
        "message_id": message_id,
        "ambiguous": False,
        "error": "",
    }


@pytest.fixture
def active(monkeypatch, tmp_path):
    monkeypatch.setenv("GOLF_PROPS_RECAP_ACTIVATION_UTC", ACTIVE)
    monkeypatch.delenv("GOLF_PROPS_DISCORD_WEBHOOK_URL", raising=False)
    # Never read the developer's live durable activation record.
    monkeypatch.setattr(gr, "default_weekly_dir", lambda: tmp_path / "weekly")
    return monkeypatch


# --------------------------------------------------------------------------
# preview
# --------------------------------------------------------------------------


def test_preview_matches_grade_manifest_and_states_roi_unavailable(tmp_path):
    recap = _recap(tmp_path)
    manifest = json.loads((GRADE_DIR / "grading_manifest.json").read_text(encoding="utf-8"))

    coverage = recap["coverage"]
    assert coverage["forecast_players"] == manifest["forecast_players"] == 120
    assert coverage["intersection_players"] == manifest["intersection_players"] == 118
    assert coverage["graded_players"] == manifest["graded_players_per_target"] == 117
    assert coverage["excluded_players"] == manifest["excluded_players"] == ["Max Greyserman"]
    assert coverage["forecast_players_without_results"] == manifest[
        "forecast_players_without_results"
    ] == ["Lanto Griffin", "Rasmus Højgaard"]
    assert {row["target"] for row in recap["targets"]} == {"top20", "top10", "top5", "winner"}
    assert all(row["graded_players"] == 117 for row in recap["targets"])

    payload = gr.recap_embed(recap)
    text = json.dumps(payload)
    lowered = text.casefold()

    assert recap["winner"] == "Austin Smotherman"
    # The page's printed window wins over the day-early schedule feed.
    assert recap["event_dates"] == {
        "start": "2026-10-22",
        "end": "2026-10-25",
        "source": "results_page",
    }
    assert "2026-10-22..2026-10-25" in gr.render_markdown(recap)
    assert "2026-10-22..2026-10-25" in text
    assert gr.event_dates_from_page(RESULTS_PAGE.read_text(encoding="utf-8")) == {
        "start": "2026-10-22",
        "end": "2026-10-25",
        "source": "results_page",
    }
    assert "priced roi unavailable" in lowered
    assert "no pre-event prices" in lowered
    assert "official priced selection list preserved" in lowered
    assert payload["embeds"][0]["footer"]["text"] == gr.FOOTER_TEXT
    # No synthetic staking, no invented prices, no model/selection claim.
    for forbidden in (r"\bstake", r"\bunits\b", r"\bprofit\b", r"\byield\b", r"\bpick\b", r"\$"):
        assert not re.search(forbidden, lowered), forbidden
    for word in PROHIBITED_WORDS:
        assert not re.search(rf"\b{word}\b", lowered), word
    assert "research cohort" in lowered

    paths = gr.preview(recap, tmp_path / "preview")
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "Austin Smotherman" in markdown
    assert "117 of 120" in markdown
    assert "Priced ROI unavailable" in markdown
    assert "Probability scores are accuracy measures, not returns." in markdown


def test_event_dates_fall_back_when_the_page_has_no_range():
    assert gr.event_dates_from_page("<html>no dates here</html>") is None
    assert gr.event_dates_from_page("") is None


def test_fingerprint_is_stable_and_tracks_finality_and_price_evidence(tmp_path):
    first = _recap(tmp_path)
    second = _recap(tmp_path)
    assert first["fingerprint"] == second["fingerprint"]
    assert len(first["fingerprint"]) == 64

    in_progress = _recap(
        tmp_path, finality={"state": "in_progress", "reason": "live_header_columns"}
    )
    assert in_progress["fingerprint"] != first["fingerprint"]

    odds_dir = tmp_path / "odds"
    odds_dir.mkdir()
    (odds_dir / "bovada_golf_20261021T120000Z.json").write_text(
        json.dumps(
            {
                "event_names": [EVENT_NAME],
                "pre_start": True,
                "captured_at_utc": "2026-10-21T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    priced = _recap(tmp_path, odds_dir=odds_dir)
    assert priced["price_availability"]["matched_snapshots"] == 1
    assert priced["price_availability"]["pre_start_snapshots"] == 1
    assert priced["price_availability"]["roi"] == "unavailable"
    assert priced["price_availability"]["selection_policy"] == "undefined"
    assert priced["fingerprint"] != first["fingerprint"]


# --------------------------------------------------------------------------
# delivery receipts
# --------------------------------------------------------------------------


def test_sent_receipt_dedupes_by_fingerprint(tmp_path, active):
    recap = _recap(tmp_path)
    calls = []

    def transport(payload, url):
        calls.append(url)
        return _ok("msg-9")

    first = gr.deliver_recap(recap, tmp_path, transport=transport, webhook_url="https://x.invalid/h", now=NOW)
    assert first["status"] == "sent"
    receipt = json.loads((tmp_path / gr.RECEIPT_NAME).read_text(encoding="utf-8"))
    assert receipt["status"] == "sent"
    assert receipt["message_id"] == "msg-9"
    assert receipt["attempts"] == 1
    assert receipt["grade_fingerprint"] == recap["fingerprint"]
    assert receipt["event_finality"] == "final"

    second = gr.deliver_recap(recap, tmp_path, transport=transport, webhook_url="https://x.invalid/h", now=NOW)
    assert second["status"] == "already_sent"
    assert len(calls) == 1


def test_known_failure_retries_then_requires_reconciliation(tmp_path, active):
    recap = _recap(tmp_path)
    calls = []

    def failing(payload, url):
        calls.append(url)
        return {"status_code": 500, "message_id": None, "ambiguous": False, "error": "HTTP 500"}

    first = gr.deliver_recap(recap, tmp_path, transport=failing, webhook_url="https://x.invalid/h", now=NOW)
    assert first["status"] == gr.STATUS_FAILED and first["receipt"]["attempts"] == 1
    second = gr.deliver_recap(recap, tmp_path, transport=failing, webhook_url="https://x.invalid/h", now=NOW)
    assert second["status"] == gr.STATUS_FAILED and second["receipt"]["attempts"] == 2
    third = gr.deliver_recap(recap, tmp_path, transport=failing, webhook_url="https://x.invalid/h", now=NOW)
    assert third["status"] == gr.STATUS_RECONCILE and third["receipt"]["attempts"] == 3
    fourth = gr.deliver_recap(recap, tmp_path, transport=failing, webhook_url="https://x.invalid/h", now=NOW)
    assert fourth["status"] == gr.STATUS_RECONCILE
    assert len(calls) == 3  # the retry cap is enforced, not exceeded


def test_ambiguous_timeout_requires_reconciliation_without_retry(tmp_path, active):
    recap = _recap(tmp_path)
    calls = []

    def ambiguous(payload, url):
        calls.append(url)
        return {
            "status_code": None,
            "message_id": None,
            "ambiguous": True,
            "error": "TimeoutError: ambiguous network outcome",
        }

    first = gr.deliver_recap(recap, tmp_path, transport=ambiguous, webhook_url="https://x.invalid/h", now=NOW)
    assert first["status"] == gr.STATUS_UNKNOWN
    assert "manual reconciliation" in " ".join(first["receipt"]["notes"])

    second = gr.deliver_recap(recap, tmp_path, transport=ambiguous, webhook_url="https://x.invalid/h", now=NOW)
    assert second["status"] == gr.STATUS_UNKNOWN
    assert len(calls) == 1


def test_legacy_grade_is_held_until_an_explicit_backfill(tmp_path, monkeypatch):
    monkeypatch.delenv("GOLF_PROPS_RECAP_ACTIVATION_UTC", raising=False)
    monkeypatch.delenv("GOLF_PROPS_DISCORD_WEBHOOK_URL", raising=False)
    recap = _recap(tmp_path)
    calls = []

    def transport(payload, url):
        calls.append(url)
        return _ok()

    held = gr.deliver_recap(recap, tmp_path, transport=transport, webhook_url="https://x.invalid/h", now=NOW)
    assert held["status"] == gr.STATUS_LEGACY_HOLD
    assert calls == []
    receipt = json.loads((tmp_path / gr.RECEIPT_NAME).read_text(encoding="utf-8"))
    assert receipt["status"] == gr.STATUS_LEGACY_HOLD
    assert receipt["attempts"] == 0

    # A second scheduled run still holds it; only the explicit flag sends.
    again = gr.deliver_recap(recap, tmp_path, transport=transport, webhook_url="https://x.invalid/h", now=NOW)
    assert again["status"] == gr.STATUS_LEGACY_HOLD and calls == []

    backfill = gr.deliver_recap(
        recap,
        tmp_path,
        transport=transport,
        webhook_url="https://x.invalid/h",
        now=NOW,
        allow_prior_grades=True,
    )
    assert backfill["status"] == "sent"
    assert len(calls) == 1


def test_pending_receipt_does_not_consume_the_final_marker(tmp_path, active):
    """A previous pending notice must not suppress the real message."""
    recap = _recap(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / gr.RECEIPT_NAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "event_key": EVENT_KEY,
                "event_name": EVENT_NAME,
                "grade_fingerprint": recap["fingerprint"],
                "status": gr.STATUS_PENDING,
                "attempts": 1,
                "notes": ["webhook not configured"],
            }
        ),
        encoding="utf-8",
    )

    result = gr.deliver_recap(
        recap, tmp_path, transport=lambda p, u: _ok("m-final"), webhook_url="https://x.invalid/h", now=NOW
    )

    assert result["status"] == "sent"
    assert result["receipt"]["message_id"] == "m-final"
    assert result["receipt"]["attempts"] == 2


def test_receipt_never_contains_the_webhook_url(tmp_path, active):
    recap = _recap(tmp_path)
    secret_url = "https://discord.example/api/webhooks/123/top-secret-token"
    gr.deliver_recap(recap, tmp_path, transport=lambda p, u: _ok(), webhook_url=secret_url, now=NOW)

    text = (tmp_path / gr.RECEIPT_NAME).read_text(encoding="utf-8")
    preview_text = (gr.preview(recap, tmp_path / "p")["json"]).read_text(encoding="utf-8")
    for value in (text, preview_text):
        assert "top-secret-token" not in value
        assert secret_url not in value


# --------------------------------------------------------------------------
# durable activation state
# --------------------------------------------------------------------------


def test_activation_state_missing_holds_every_grade(tmp_path, monkeypatch):
    monkeypatch.delenv(gr.ACTIVATION_ENV, raising=False)
    weekly = tmp_path / "weekly"
    assert gr.load_activation_state(gr.activation_state_path(weekly))["status"] == "missing"
    assert gr.resolve_activation(weekly)["source"] == "uninitialized"

    calls = []
    recap = _recap(tmp_path)
    result = gr.deliver_recap(
        recap,
        tmp_path / "delivery",
        transport=lambda p, u: calls.append(u) or _ok(),
        webhook_url="https://x.invalid/h",
        now=NOW,
        weekly_dir=weekly,
    )
    assert result["status"] == gr.STATUS_LEGACY_HOLD
    assert calls == []
    receipt = json.loads((tmp_path / "delivery" / gr.RECEIPT_NAME).read_text())
    assert receipt["attempts"] == 0
    assert receipt["activation"]["source"] == "uninitialized"
    assert "uninitialized" in " ".join(receipt["notes"])


def test_initialization_is_once_only_and_atomic(tmp_path):
    weekly = tmp_path / "weekly"
    path = gr.activation_state_path(weekly)
    first = gr.initialize_activation_state(path, now=gr._parse_iso("2026-10-27T00:00:00Z"))
    assert first["result"] == "initialized"
    assert first["activation_utc"] == "2026-10-27T00:00:00Z"
    raw = path.read_bytes()
    assert not (weekly / (gr.ACTIVATION_STATE_NAME + ".tmp")).exists()

    # A later initialization must not move the threshold.
    second = gr.initialize_activation_state(
        path, now=gr._parse_iso("2026-11-15T00:00:00Z")
    )
    assert second["result"] == "unchanged"
    assert second["activation_utc"] == "2026-10-27T00:00:00Z"
    assert path.read_bytes() == raw


def test_corrupt_activation_state_holds_and_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.delenv(gr.ACTIVATION_ENV, raising=False)
    weekly = tmp_path / "weekly"
    path = gr.activation_state_path(weekly)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    before = path.read_bytes()

    assert gr.load_activation_state(path)["status"] == "corrupt"
    resolved = gr.resolve_activation(weekly)
    assert resolved["source"] == "corrupt_state"
    assert resolved["activation_utc"] is None

    recap = _recap(tmp_path)
    calls = []
    held = gr.deliver_recap(
        recap,
        tmp_path / "delivery",
        transport=lambda p, u: calls.append(u) or _ok(),
        webhook_url="https://x.invalid/h",
        now=NOW,
        weekly_dir=weekly,
    )
    assert held["status"] == gr.STATUS_LEGACY_HOLD
    assert calls == []
    with pytest.raises(gr.ActivationStateError):
        gr.initialize_activation_state(path, now=NOW)
    assert path.read_bytes() == before


def test_valid_activation_admits_a_later_grade(tmp_path, monkeypatch):
    monkeypatch.delenv(gr.ACTIVATION_ENV, raising=False)
    weekly = tmp_path / "weekly"
    gr.initialize_activation_state(
        gr.activation_state_path(weekly), now=gr._parse_iso("2026-10-01T00:00:00Z")
    )
    recap = _recap(tmp_path)
    calls = []
    sent = gr.deliver_recap(
        recap,
        tmp_path / "delivery",
        transport=lambda p, u: calls.append(u) or _ok("msg-42"),
        webhook_url="https://x.invalid/h",
        now=NOW,
        weekly_dir=weekly,
    )
    assert sent["status"] == "sent"
    assert len(calls) == 1
    assert sent["receipt"]["activation"]["source"] == "durable_state"
    assert sent["receipt"]["message_id"] == "msg-42"


def test_env_compat_still_works_without_a_state_file(tmp_path, active):
    recap = _recap(tmp_path)
    result = gr.deliver_recap(
        recap,
        tmp_path,
        transport=lambda p, u: _ok(),
        webhook_url="https://x.invalid/h",
        now=NOW,
        weekly_dir=tmp_path / "no-weekly",
    )
    assert result["status"] == "sent"
    receipt = json.loads((tmp_path / gr.RECEIPT_NAME).read_text())
    assert receipt["activation"]["source"] == "env_compat"


# --------------------------------------------------------------------------
# authorised demo label and readback
# --------------------------------------------------------------------------


def test_demo_label_is_authorised_only_for_the_bermuda_event(tmp_path):
    assert gr.demo_label_for(EVENT_KEY) == gr.DEMO_LABEL
    with pytest.raises(gr.GradeRecapError, match="no demo publication"):
        gr.demo_label_for("some_other_event_2026")
    with pytest.raises(gr.GradeRecapError, match="no demo publication"):
        gr.build_recap(
            event_key="some_other_event_2026",
            event_name="Some Other Event",
            grading_dir=GRADE_DIR,
            results_page=RESULTS_PAGE,
            demo_label=gr.DEMO_LABEL,
        )


def test_demo_recap_is_labelled_with_archived_dates_and_real_coverage(tmp_path):
    recap = _recap(tmp_path, demo_label=gr.DEMO_LABEL)
    assert recap["coverage"]["graded_players"] == 117
    assert recap["coverage"]["forecast_players"] == 120
    assert recap["winner"] == "Austin Smotherman"
    assert recap["event_dates"]["start"] == "2026-10-22"
    assert recap["event_dates"]["end"] == "2026-10-25"
    assert recap["price_availability"]["roi"] == "unavailable"
    assert recap["fingerprint"] != _recap(tmp_path)["fingerprint"]

    payload = gr.recap_embed(recap)
    embed = payload["embeds"][0]
    assert embed["title"].startswith(gr.DEMO_LABEL)
    delivery_field = next(f for f in embed["fields"] if f["name"] == "Delivery")
    assert gr.DEMO_LABEL in delivery_field["value"]
    assert "2026-10-22..2026-10-25" in delivery_field["value"]
    encoded = json.dumps(payload).casefold()
    assert "117 of 120" in encoded
    assert "priced roi unavailable" in encoded

    markdown = gr.render_markdown(recap)
    assert "End-to-end verification demo" in markdown
    assert "archived real grade" in markdown
    assert "2026-10-22..2026-10-25" in markdown


def test_readback_returns_a_sanitised_digest_only(monkeypatch):
    secret = "https://discord.example/api/webhooks/123/top-secret-token"
    seen = {}

    def fetch(url):
        seen["url"] = url
        return (
            200,
            json.dumps(
                {
                    "id": "msg-77",
                    "channel_id": "chan-1",
                    "content": "final grade recap",
                    "embeds": [{"title": "x"}],
                }
            ),
        )

    result = gr.readback_message("msg-77", webhook_url=secret, fetch=fetch)
    assert seen["url"] == secret + "/messages/msg-77"
    assert result["status"] == "ok"
    assert result["message_id"] == "msg-77"
    assert result["channel_id"] == "chan-1"
    assert result["embeds"] == 1
    assert result["content_length"] == len("final grade recap")
    encoded = json.dumps(result)
    assert "top-secret-token" not in encoded
    assert secret not in encoded
    assert "discord.example" not in encoded


def test_cli_initializes_activation_without_side_effects(tmp_path, capsys):
    from golf_props.cli import main

    weekly = tmp_path / "weekly"
    argv = ["init-grade-recap-activation", "--weekly-dir", str(weekly)]
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "grade_recap_activation_result=initialized" in out
    state = json.loads((weekly / gr.ACTIVATION_STATE_NAME).read_text(encoding="utf-8"))
    assert state["activation_utc"]
    assert sorted(p.name for p in weekly.iterdir()) == [gr.ACTIVATION_STATE_NAME]

    assert main(argv) == 0
    assert "grade_recap_activation_result=unchanged" in capsys.readouterr().out


def test_repeat_dry_run_after_a_sent_receipt_says_deduped(tmp_path, active):
    recap = _recap(tmp_path)
    calls = []
    gr.deliver_recap(
        recap,
        tmp_path,
        transport=lambda p, u: calls.append(u) or _ok("msg-9"),
        webhook_url="https://x.invalid/h",
        now=NOW,
    )
    state = gr.preview_delivery_state(recap, tmp_path)
    assert state["state"] == "already_sent"
    assert state["send"] is False
    assert "deduped" in state["reason"]

    again = gr.deliver_recap(
        recap,
        tmp_path,
        transport=lambda p, u: calls.append(u) or _ok(),
        webhook_url="https://x.invalid/h",
        now=NOW,
    )
    assert again["status"] == "already_sent"
    assert len(calls) == 1


# --------------------------------------------------------------------------
# results-page identity, page window and publish gates (blocking regression)
# --------------------------------------------------------------------------

LIVE_RESULTS = FIXTURES / "golf_recap_live_results"
LIVE_BERMUDA = LIVE_RESULTS / "31000146_butterfield-bermuda-championship.html"
LIVE_SENTRY = LIVE_RESULTS / "31000071_the-sentry.html"
LIVE_PAGE_SHA = "e216d82a38ec0d77e14b374d79688f7cafe019af552840582134671b79211bfe"
OCT_WINDOW = {"start": "2026-10-22", "end": "2026-10-24", "source": "event_control"}


def _page_without_winner() -> str:
    header = (
        "<table><thead><tr><th></th><th>pos</th><th>ctry</th><th>name</th>"
        "<th>to par</th><th>earnings</th><th>r1</th><th>r2</th><th>r3</th>"
        "<th>r4</th><th>total</th></tr></thead><tbody>"
    )
    rows = []
    for position, name in (("T2", "Alpha One"), ("T2", "Beta Two")):
        cells = ["", position, "", name, "E", "$1", "70", "70", "70", "70", "280"]
        rendered = []
        for index, value in enumerate(cells):
            if index == 3:
                rendered.append(
                    '<td><span class="CellPlayerName--long"><a>' + value + "</a></span></td>"
                )
            else:
                rendered.append(f"<td>{value}</td>")
        rows.append(
            '<tr class="TableBase-bodyTr GolfLeaderboard-bodyTr">'
            + "".join(rendered)
            + "</tr>"
        )
    return header + "".join(rows) + "</tbody></table>"


def _pending_recap(tmp_path, *, page_html, finality, demo_label=None, evidence=None):
    page = tmp_path / "cbs_final_leaderboard.html"
    page.write_text(page_html, encoding="utf-8")
    return gr.build_recap(
        event_key=EVENT_KEY,
        event_name=EVENT_NAME,
        grading_dir=GRADE_DIR,
        results_page=page,
        event_dates=OCT_WINDOW,
        finality=finality,
        odds_archive_dir=tmp_path / "no-odds",
        demo_label=demo_label,
        results_evidence=evidence,
    )


def test_page_window_is_read_from_the_leaderboard_hud_only():
    # A document-level JSON-LD/navigation date must never become the event window.
    html = (
        '<script type="application/ld+json">{"startDate": "Jan 8-11, 2026"}</script>'
        '<nav><span>Jan 8-11, 2026</span></nav>'
        '<div class="GolfLeaderboard-hudItem GolfLeaderboard-hudDateRange">'
        " Oct 22-25, 2026 </div>"
    )
    assert gr.page_event_window(html) == {"start": "2026-10-22", "end": "2026-10-25"}
    assert gr.event_dates_from_page(html) == {
        "start": "2026-10-22",
        "end": "2026-10-25",
        "source": "results_page",
    }
    # No HUD at all -> no window, even if the document has a date elsewhere.
    assert gr.page_event_window("<nav>Jan 8-11, 2026</nav>") is None
    assert gr.event_dates_from_page("<nav>Jan 8-11, 2026</nav>") is None
    # Two contradictory HUD windows are ambiguous.
    two = html + (
        '<div class="GolfLeaderboard-hudItem GolfLeaderboard-hudDateRange">'
        " Jan 8-11, 2026 </div>"
    )
    assert gr.page_event_window(two) is None


def test_wrong_event_page_window_is_rejected_against_event_control():
    sentry = LIVE_SENTRY.read_text(encoding="utf-8")
    assert gr.page_event_window(sentry) == {"start": "2026-01-08", "end": "2026-01-11"}
    check = gr.window_check(gr.page_event_window(sentry), OCT_WINDOW)
    assert check["checked"] is True and check["consistent"] is False
    assert "2026-01-08" in check["reason"]
    assert gr.event_dates_from_page(sentry, expected=OCT_WINDOW) is None
    # The correct page agrees with the event control window (schedule end was a
    # day early: page 10-25 vs control 10-24).
    bermuda = LIVE_BERMUDA.read_text(encoding="utf-8")
    assert gr.window_check(gr.page_event_window(bermuda), OCT_WINDOW)["consistent"] is True
    assert gr.event_dates_from_page(bermuda, expected=OCT_WINDOW) == {
        "start": "2026-10-22",
        "end": "2026-10-25",
        "source": "results_page",
    }


def test_graded_results_page_is_selected_by_manifest_hash(tmp_path):
    import shutil

    manifest = json.loads((GRADE_DIR / "grading_manifest.json").read_text(encoding="utf-8"))
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    shutil.copy2(LIVE_SENTRY, results_dir / LIVE_SENTRY.name)
    shutil.copy2(LIVE_BERMUDA, results_dir / LIVE_BERMUDA.name)

    page, evidence = gr.resolve_graded_results_page(results_dir, manifest)
    assert page == results_dir / LIVE_BERMUDA.name
    assert evidence["verified"] is True
    assert evidence["sha256"] == LIVE_PAGE_SHA
    assert evidence["source_event_id"] == "31000146"

    # Same bytes under another event's CBS id must not be accepted.
    wrong_name = results_dir / "31000071_the-sentry.html"
    wrong_name.write_bytes((results_dir / LIVE_BERMUDA.name).read_bytes())
    (results_dir / LIVE_BERMUDA.name).unlink()
    page, evidence = gr.resolve_graded_results_page(results_dir, manifest)
    assert page is None
    assert evidence["verified"] is False
    assert "different CBS event" in evidence["reason"]

    # Two copies of the graded bytes are ambiguous, not a licence to pick one.
    results_dir.mkdir(exist_ok=True)
    shutil.copy2(LIVE_BERMUDA, results_dir / LIVE_BERMUDA.name)
    shutil.copy2(LIVE_BERMUDA, results_dir / "31000146_bermuda-copy.html")
    page, evidence = gr.resolve_graded_results_page(results_dir, manifest)
    assert page is None
    assert "ambiguous results page" in evidence["reason"]


def test_unknown_finality_demo_cannot_be_forced_out_by_prior_grade_flag(tmp_path):
    recap = _pending_recap(
        tmp_path,
        page_html=_page_without_winner(),
        finality={"state": "unknown", "reason": "player_leaderboard_table_not_found"},
        demo_label=gr.DEMO_LABEL,
    )
    assert recap["winner"] is None and recap["winner_rows"] == 0
    assert recap["event_finality"]["state"] == "unknown"
    assert "event finality is unknown" in " ".join(gr.recap_release_blockers(recap))
    payload = gr.recap_embed(recap)
    embed = payload["embeds"][0]
    assert "Grade Recap (pending)" in embed["title"]
    assert embed["description"].endswith("unknown | winner not recorded")
    assert any(field["name"] == "Status" for field in embed["fields"])
    assert "publication blocked" in gr.render_markdown(recap).casefold()

    calls = []
    with pytest.raises(gr.GradeRecapError, match="not publishable"):
        gr.deliver_recap(
            recap,
            tmp_path / "delivery",
            transport=lambda p, u: calls.append(u) or _ok(),
            webhook_url="https://x.invalid/h",
            now=NOW,
            allow_prior_grades=True,
            require_results_evidence=False,
        )
    assert calls == []
    assert not (tmp_path / "delivery" / gr.RECEIPT_NAME).exists()


def test_winner_must_be_unique_before_a_recap_is_published(tmp_path):
    tie_page = _page_without_winner().replace("T2", "1")
    recap = _pending_recap(
        tmp_path,
        page_html=tie_page,
        finality={"state": "final", "reason": "earnings_column_settled"},
    )
    assert recap["winner"] is None and recap["winner_rows"] == 2
    assert "winner is not definitively identified" in " ".join(
        gr.recap_release_blockers(recap)
    )
    calls = []
    with pytest.raises(gr.GradeRecapError):
        gr.deliver_recap(
            recap,
            tmp_path / "delivery",
            transport=lambda p, u: calls.append(u) or _ok(),
            webhook_url="https://x.invalid/h",
            now=NOW,
        )
    assert calls == []


def test_pipeline_send_requires_the_results_page_evidence(tmp_path):
    page_html = _page_without_winner().replace("T2", "1", 1)
    unverified = _pending_recap(
        tmp_path,
        page_html=page_html,
        finality={"state": "final", "reason": "earnings_column_settled"},
        evidence={"verified": False, "reason": "page sha256 does not match"},
    )
    calls = []
    with pytest.raises(gr.GradeRecapError, match="not publishable"):
        gr.deliver_recap(
            unverified,
            tmp_path / "delivery",
            transport=lambda p, u: calls.append(u) or _ok(),
            webhook_url="https://x.invalid/h",
            now=NOW,
            allow_prior_grades=True,
            require_results_evidence=True,
        )
    assert calls == []
    assert gr.preview_delivery_state(
        unverified, tmp_path / "delivery", require_results_evidence=True
    )["state"] == "blocked_pending"

    verified = _pending_recap(
        tmp_path,
        page_html=page_html,
        finality={"state": "final", "reason": "earnings_column_settled"},
        evidence={"verified": True, "reason": "page sha256 matches the grade manifest"},
    )
    result = gr.deliver_recap(
        verified,
        tmp_path / "delivery2",
        transport=lambda p, u: calls.append(u) or _ok("msg-v"),
        webhook_url="https://x.invalid/h",
        now=NOW,
        allow_prior_grades=True,
        require_results_evidence=True,
    )
    assert result["status"] == "sent" and len(calls) == 1



def test_price_availability_reports_actual_preserved_markets_not_a_fixed_claim(tmp_path):
    odds_dir = tmp_path / "odds"
    odds_dir.mkdir()
    rows = [
        {"event_name": EVENT_NAME, "market_type": market}
        for market in ("winner", "winner", "top5", "top10", "top20", "top20", "top20")
    ]
    (odds_dir / "bovada_golf_20261021T120000Z.json").write_text(
        json.dumps(
            {
                "event_names": [EVENT_NAME],
                "pre_start": True,
                "captured_at_utc": "2026-10-21T12:00:00Z",
                "rows": rows,
            }
        ),
        encoding="utf-8",
    )
    recap = _recap(tmp_path, odds_dir=odds_dir)
    availability = recap["price_availability"]
    assert availability["roi"] == "unavailable"
    assert availability["market_counts"] == {
        "top10": 1,
        "top20": 3,
        "top5": 1,
        "winner": 2,
    }
    assert "top5" in availability["market_coverage"]
    assert "winner market only" not in availability["market_coverage"]
    assert availability["pre_start_snapshots"] == 1
    assert "no official priced selection" in availability["statement"]
