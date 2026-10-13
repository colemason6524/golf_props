"""Tests for golf_props.ingestion.espn_withdrawals (fixture-based, no network)."""
import csv
from pathlib import Path

import pytest

import golf_props.ingestion.espn_withdrawals as wd_mod
from golf_props.ingestion.espn_withdrawals import (
    _is_out,
    fetch_withdrawals,
    filter_field_withdrawals,
)


@pytest.mark.parametrize("status,expected", [
    ({"displayValue": "WD", "type": {"name": "STATUS_WITHDRAW"}}, True),
    ({"displayValue": "DQ", "type": {"name": "STATUS_DISQUALIFIED"}}, True),
    ({"displayValue": "wd"}, True),
    ({"displayValue": "", "type": {"name": "STATUS_WITHDRAW"}}, True),
    ({"displayValue": "F", "type": {"name": "STATUS_FINISH"}}, False),
    ({"displayValue": "CUT"}, False),
    ({}, False),
])
def test_is_out(status, expected):
    assert _is_out(status)[0] is expected


def _leaderboard_payload(entries):
    return {"events": [{
        "name": "Test Classic",
        "competitions": [{
            "competitors": [
                {"athlete": {"displayName": name}, "status": status}
                for name, status in entries
            ],
        }],
    }]}


def test_fetch_withdrawals_parses_fixture(monkeypatch):
    payload = _leaderboard_payload([
        ("Xander Schauffele",
         {"displayValue": "F", "type": {"name": "STATUS_FINISH"}}),
        ("Min Woo Lee",
         {"displayValue": "WD", "type": {"name": "STATUS_WITHDRAW"}}),
        ("John Pak",
         {"displayValue": "DQ", "type": {"name": "STATUS_DISQUALIFIED"}}),
    ])
    monkeypatch.setattr(wd_mod, "_espn_get", lambda url: (payload, None))
    withdrawals, diag = fetch_withdrawals()
    assert diag["status"] == "ok"
    assert diag["players_seen"] == 3
    by_player = {w["player"]: w for w in withdrawals}
    assert set(by_player) == {"Min Woo Lee", "John Pak"}
    assert by_player["Min Woo Lee"]["status"] == "WD"
    assert by_player["Min Woo Lee"]["key"]


def test_fetch_withdrawals_fail_open(monkeypatch):
    monkeypatch.setattr(wd_mod, "_espn_get", lambda url: (None, "boom"))
    withdrawals, diag = fetch_withdrawals()
    assert withdrawals == []
    assert diag["status"] == "failed"
    assert diag["error"]


def _write_field_csv(path: Path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["player_id", "player_name", "entry_status"])
        writer.writeheader()
        writer.writerows(rows)


def test_filter_removes_entry_status_withdrawn(tmp_path):
    fp = tmp_path / "field.csv"
    _write_field_csv(fp, [
        {"player_id": "1", "player_name": "Xander Schauffele",
         "entry_status": "confirmed"},
        {"player_id": "2", "player_name": "John Pak",
         "entry_status": "withdrawn"},
    ])
    removed, diag = filter_field_withdrawals(fp, withdrawals=[], fetch=False)
    assert [r["player_name"] for r in removed] == ["John Pak"]
    assert "pga tour field" in removed[0]["reason"]
    rows = list(csv.DictReader(fp.open()))
    assert [r["player_name"] for r in rows] == ["Xander Schauffele"]
    assert diag["field_size_before"] == 2
    assert diag["field_size_after"] == 1


def test_filter_removes_espn_wd(tmp_path):
    fp = tmp_path / "field.csv"
    _write_field_csv(fp, [
        {"player_id": "1", "player_name": "Xander Schauffele",
         "entry_status": "confirmed"},
        {"player_id": "3", "player_name": "Min Woo Lee",
         "entry_status": "confirmed"},
    ])
    fake_wd = [{"player": "Min Woo Lee", "key": "minwoolee", "status": "WD"}]
    removed, diag = filter_field_withdrawals(fp, withdrawals=fake_wd,
                                             fetch=False)
    assert [r["player_name"] for r in removed] == ["Min Woo Lee"]
    assert "espn" in removed[0]["reason"]
    rows = list(csv.DictReader(fp.open()))
    assert [r["player_name"] for r in rows] == ["Xander Schauffele"]


def test_filter_no_removals_leaves_file_untouched(tmp_path):
    fp = tmp_path / "field.csv"
    _write_field_csv(fp, [
        {"player_id": "1", "player_name": "Xander Schauffele",
         "entry_status": "confirmed"},
    ])
    before = fp.read_bytes()
    removed, diag = filter_field_withdrawals(fp, withdrawals=[], fetch=False)
    assert removed == []
    assert fp.read_bytes() == before
    assert diag["removed"] == 0


def test_filter_fail_open_missing_file(tmp_path):
    removed, diag = filter_field_withdrawals(tmp_path / "missing.csv",
                                             withdrawals=[], fetch=False)
    assert removed == []
    assert diag["status"] == "failed"
