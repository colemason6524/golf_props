from datetime import datetime, timezone

import pytest

from golf_props.events.event_control import (
    STATE_AWAITING_FIELD,
    STATE_BLOCKED,
    STATE_DISCOVERED,
    STATE_FORECAST_ARCHIVED,
    EventControl,
)


def test_transition_records_history_and_clears_blocking_reason(tmp_path):
    ec = EventControl(event_key="test_2025", state=STATE_DISCOVERED)
    now = datetime(2025, 4, 30, tzinfo=timezone.utc)
    ec.transition(STATE_AWAITING_FIELD, "awaiting field", now)
    assert ec.state == STATE_AWAITING_FIELD
    assert ec.history[-1]["from_state"] == STATE_DISCOVERED
    ec.transition(STATE_BLOCKED, "problem", now)
    assert ec.blocking_reason == "problem"
    ec.transition(STATE_AWAITING_FIELD, "fixed", now)
    assert ec.blocking_reason == ""


def test_terminal_state_is_locked():
    ec = EventControl(state=STATE_FORECAST_ARCHIVED)
    with pytest.raises(ValueError, match="terminal"):
        ec.transition(STATE_DISCOVERED, "nope")


def test_invalid_transition_raises():
    ec = EventControl(state=STATE_AWAITING_FIELD)
    with pytest.raises(ValueError, match="invalid state transition"):
        ec.transition(STATE_FORECAST_ARCHIVED, "skip")


def test_save_load_round_trip(tmp_path):
    path = tmp_path / "event_control.json"
    ec = EventControl(
        event_key="tour_2026",
        event_name="TOUR Championship",
        season=2026,
        state=STATE_DISCOVERED,
    )
    ec.save(path)
    loaded = EventControl.load(path)
    assert loaded is not None
    assert loaded.event_key == "tour_2026"
    assert loaded.season == 2026
    assert loaded.state == STATE_DISCOVERED


def test_load_missing_or_bad_file_returns_none(tmp_path):
    assert EventControl.load(tmp_path / "missing.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert EventControl.load(bad) is None
