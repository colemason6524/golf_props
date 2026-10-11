"""Dedupe for urgent ops alerts: identical text is sent once per 24h window."""

import json
from datetime import datetime, timedelta, timezone

import golf_props.notifications.discord as discord
from golf_props.notifications.discord import (
    ALERT_DEDUPE_WINDOW_SECONDS,
    send_ops_alert,
)

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
MSG_A = "golf forecast discovery could not finish; will retry next run"
MSG_B = "golf forecast is blocked; check status for details"


class _Response:
    status = 204

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _setup(monkeypatch, tmp_path, calls):
    def fake_urlopen(request, timeout=20):
        calls.append(request.data.decode("utf-8"))
        return _Response()

    monkeypatch.setenv(
        "GOLF_PROPS_DISCORD_WEBHOOK_URL", "https://main.example/webhook"
    )
    monkeypatch.setattr(discord, "urlopen", fake_urlopen)
    monkeypatch.setenv(
        "GOLF_PROPS_OPS_ALERT_LEDGER", str(tmp_path / "ops_alerts.json")
    )


def test_repeat_alert_suppressed_within_window(tmp_path, monkeypatch):
    calls: list[str] = []
    _setup(monkeypatch, tmp_path, calls)

    assert send_ops_alert(MSG_A, _now=NOW) is True
    assert send_ops_alert(MSG_A, _now=NOW + timedelta(hours=2)) is False
    assert send_ops_alert(MSG_A, _now=NOW + timedelta(hours=23)) is False

    assert len(calls) == 1
    ledger = json.loads((tmp_path / "ops_alerts.json").read_text(encoding="utf-8"))
    assert len(ledger) == 1


def test_repeat_alert_resends_after_window(tmp_path, monkeypatch):
    calls: list[str] = []
    _setup(monkeypatch, tmp_path, calls)

    assert send_ops_alert(MSG_A, _now=NOW) is True
    later = NOW + timedelta(seconds=ALERT_DEDUPE_WINDOW_SECONDS + 1)
    assert send_ops_alert(MSG_A, _now=later) is True

    assert len(calls) == 2


def test_distinct_alerts_both_sent(tmp_path, monkeypatch):
    calls: list[str] = []
    _setup(monkeypatch, tmp_path, calls)

    assert send_ops_alert(MSG_A, _now=NOW) is True
    assert send_ops_alert(MSG_B, _now=NOW + timedelta(hours=2)) is True

    assert len(calls) == 2
    ledger = json.loads((tmp_path / "ops_alerts.json").read_text(encoding="utf-8"))
    assert len(ledger) == 2


def test_corrupt_ledger_still_sends(tmp_path, monkeypatch):
    calls: list[str] = []
    _setup(monkeypatch, tmp_path, calls)
    (tmp_path / "ops_alerts.json").write_text("not json{{{", encoding="utf-8")

    assert send_ops_alert(MSG_A, _now=NOW) is True
    assert len(calls) == 1


def test_failed_delivery_does_not_mark_sent(tmp_path, monkeypatch):
    calls: list[str] = []
    _setup(monkeypatch, tmp_path, calls)

    def boom(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(discord, "urlopen", boom)
    monkeypatch.setattr(discord.time, "sleep", lambda *_: None)

    assert send_ops_alert(MSG_A, _now=NOW) is False
    # Ledger records only successful deliveries, so the next attempt retries.
    assert not (tmp_path / "ops_alerts.json").exists()
