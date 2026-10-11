import csv
import json
from pathlib import Path

import pytest

from golf_props.notifications.discord import (
    DiscordBoardError,
    build_board,
    discord_payload,
    publish_board,
    render_markdown,
    send_ops_alert,
)


@pytest.fixture(autouse=True)
def _isolated_ops_alert_ledger(tmp_path, monkeypatch):
    # Ops-alert dedupe persists in data/interim/weekly/ops_alerts.json; keep
    # tests hermetic so alert tests never see each other's deliveries.
    monkeypatch.setenv(
        "GOLF_PROPS_OPS_ALERT_LEDGER", str(tmp_path / "ops_alerts.json")
    )


def _archive(tmp_path: Path, classification: str = "prospective_forecast", timing_source: str = "exact_tee_times") -> Path:
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "archive_manifest.json").write_text(json.dumps({"files": {}}))
    (archive / "run_manifest.json").write_text(json.dumps({
        "event_name": "Test Championship",
        "created_at_utc": "2026-09-16T12:00:00+00:00",
        "event_start_at_utc": "2026-09-17T11:20:00+00:00",
        "timing_source": timing_source,
        "pre_start_verified": True,
        "eligibility": {"classification": classification, "event_date": "2026-09-17"},
        "event_structure": {"format": "72_hole_stroke_play", "cut_rule": "top_n_and_ties"},
        "frozen_parameters": {"half_life_days": 365, "prior_rounds": 8, "variance_prior_rounds": 20, "source_data_through": "2026-07-11"},
        "field_quality": {"quality_status": "ok"},
    }))
    with (archive / "predictions.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["player_name", "winner_prob", "top5_prob", "top10_prob", "top20_prob", "make_cut_prob"])
        writer.writeheader()
        writer.writerows([
            {"player_name": "Player B", "winner_prob": ".10", "top5_prob": ".30", "top10_prob": ".50", "top20_prob": ".80", "make_cut_prob": ".90"},
            {"player_name": "Player A", "winner_prob": ".20", "top5_prob": ".40", "top10_prob": ".60", "top20_prob": ".70", "make_cut_prob": ".95"},
        ])
    return archive


def test_board_requires_prospective_archive(tmp_path, monkeypatch):
    archive = _archive(tmp_path, "retrospective_replay")
    monkeypatch.setattr("golf_props.notifications.discord.verify_forecast_archive", lambda _: {"verified": True, "problems": []})
    with pytest.raises(DiscordBoardError, match="prospective"):
        build_board(archive)


def test_board_renders_ranked_forecasts_without_recommendation_language(tmp_path, monkeypatch):
    archive = _archive(tmp_path)
    monkeypatch.setattr("golf_props.notifications.discord.verify_forecast_archive", lambda _: {"verified": True, "problems": []})
    board = build_board(archive)
    assert board["rows"][0]["player_name"] == "Player B"
    payload = discord_payload(board)
    encoded = json.dumps(payload).casefold()
    assert "prices omitted" in encoded
    assert "lock" not in encoded
    assert "wager" not in encoded
    assert "edge" not in encoded
    assert "Player B" in render_markdown(board)


def test_dry_run_writes_receipt_and_deduplicates(tmp_path, monkeypatch, capsys):
    archive = _archive(tmp_path)
    monkeypatch.setattr("golf_props.notifications.discord.verify_forecast_archive", lambda _: {"verified": True, "problems": []})
    output = tmp_path / "delivery"
    result = publish_board(archive, output, dry_run=True)
    assert result["receipt_data"]["status"] == "dry_run"
    assert (output / "forecast_board.json").exists()
    assert json.loads((output / "delivery_receipt.json").read_text())["messages"] == 0
    with pytest.raises(DiscordBoardError, match="already has"):
        publish_board(archive, output, dry_run=True)
    assert "Test Championship" in capsys.readouterr().out


def test_board_displays_timing_source(tmp_path, monkeypatch):
    archive = _archive(tmp_path, timing_source="exact_tee_times")
    monkeypatch.setattr("golf_props.notifications.discord.verify_forecast_archive", lambda _: {"verified": True, "problems": []})
    board = build_board(archive)
    assert board["timing_source"] == "exact_tee_times"
    payload = discord_payload(board)
    # Verify timing source field exists in embed
    fields = payload["embeds"][0]["fields"]
    timing_field = next((f for f in fields if f["name"] == "Timing source"), None)
    assert timing_field is not None
    assert timing_field["value"] == "exact tee times"
    # Verify markdown rendering
    markdown = render_markdown(board)
    assert "Timing source: `exact tee times`" in markdown


def test_board_displays_schedule_date_fallback(tmp_path, monkeypatch):
    archive = _archive(tmp_path, timing_source="schedule_date_fallback")
    monkeypatch.setattr("golf_props.notifications.discord.verify_forecast_archive", lambda _: {"verified": True, "problems": []})
    board = build_board(archive)
    assert board["timing_source"] == "schedule_date_fallback"
    payload = discord_payload(board)
    # Verify timing source field exists in embed
    fields = payload["embeds"][0]["fields"]
    timing_field = next((f for f in fields if f["name"] == "Timing source"), None)
    assert timing_field is not None
    assert timing_field["value"] == "official event date"
    # Verify markdown rendering
    markdown = render_markdown(board)
    assert "Timing source: `official event date`" in markdown


def test_urgent_alert_uses_main_webhook_with_prefix(tmp_path, monkeypatch):
    import golf_props.notifications.discord as discord

    sent = {}

    class _Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=20):
        sent["url"] = request.full_url
        sent["body"] = request.data.decode("utf-8")
        return _Response()

    monkeypatch.delenv("GOLF_PROPS_DISCORD_OPS_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("GOLF_PROPS_DISCORD_WEBHOOK_URL", "https://main.example/webhook")
    monkeypatch.setattr(discord, "urlopen", fake_urlopen)

    assert send_ops_alert("golf forecast deadline missed: Test Invitational") is True
    assert sent["url"] == "https://main.example/webhook"
    payload = json.loads(sent["body"])
    assert payload["content"].startswith("[URGENT]")
    assert payload["allowed_mentions"] == {"parse": []}


def test_urgent_alert_suppressed_without_any_webhook(monkeypatch):
    monkeypatch.delenv("GOLF_PROPS_DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("GOLF_PROPS_DISCORD_OPS_WEBHOOK_URL", raising=False)
    assert send_ops_alert("deadline missed") is False


def test_urgent_alert_delivery_failure_is_isolated(monkeypatch):
    import golf_props.notifications.discord as discord

    def boom(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setenv("GOLF_PROPS_DISCORD_WEBHOOK_URL", "https://main.example/webhook")
    monkeypatch.setattr(discord, "urlopen", boom)
    monkeypatch.setattr(discord.time, "sleep", lambda *_: None)

    # A failed alert must return False and never raise into the forecast loop.
    assert send_ops_alert("hard pipeline error") is False


def test_urgent_alert_scrubs_raw_exception_text(tmp_path, monkeypatch):
    import golf_props.notifications.discord as discord

    sent = {}

    class _Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=20):
        sent["body"] = request.data.decode("utf-8")
        return _Response()

    monkeypatch.setenv("GOLF_PROPS_DISCORD_WEBHOOK_URL", "https://main.example/webhook")
    monkeypatch.setattr(discord, "urlopen", fake_urlopen)

    raw = "golf post-event grading failed for Baycurrent Classic (baycurrent_classic_2026): ValueError: could not convert string to float: \'3*\'"
    assert send_ops_alert(raw) is True
    payload = json.loads(sent["body"])
    assert "ValueError" not in payload["content"]
    assert "could not convert string to float" not in payload["content"]
    assert payload["content"].startswith("[URGENT]")
