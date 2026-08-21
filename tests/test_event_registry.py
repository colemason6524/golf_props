import csv

import pytest

from golf_props.events.structure import (
    CUT_RULE_NO_CUT,
    CUT_RULE_TOP_N_AND_TIES,
    EventRegistryError,
    read_registry,
    resolve_structure,
    scope_status,
)


def write_registry(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


ROWS = [
    {
        "season": "2025",
        "source_event_id": "",
        "event_name": "Test Invitational",
        "include": "1",
        "format": "72_hole_stroke_play",
        "rounds": "4",
        "cut_rule": "top_n_and_ties",
        "cut_size": "65",
        "decision_status": "reviewed",
        "reviewed_at_utc": "2025-01-01T00:00:00Z",
        "notes": "",
    },
    {
        "season": "2025",
        "source_event_id": "",
        "event_name": "Playoff Finale",
        "include": "1",
        "format": "72_hole_stroke_play",
        "rounds": "4",
        "cut_rule": "no_cut",
        "cut_size": "0",
        "decision_status": "reviewed",
        "reviewed_at_utc": "2025-01-01T00:00:00Z",
        "notes": "",
    },
    {
        "season": "2025",
        "source_event_id": "",
        "event_name": "Team Cup",
        "include": "0",
        "format": "",
        "rounds": "",
        "cut_rule": "",
        "cut_size": "",
        "decision_status": "reviewed",
        "reviewed_at_utc": "2025-01-01T00:00:00Z",
        "notes": "excluded",
    },
]


def test_scope_status(tmp_path):
    path = tmp_path / "registry.csv"
    write_registry(path, ROWS)
    rows = read_registry(path)
    assert scope_status(rows, 2025, "Test Invitational") is True
    assert scope_status(rows, 2025, "Team Cup") is False
    assert scope_status(rows, 2025, "Unlisted Event") is None


def test_resolve_structure_reviewed_no_cut(tmp_path):
    path = tmp_path / "registry.csv"
    write_registry(path, ROWS)
    rows = read_registry(path)
    decision = resolve_structure(rows, 2025, "Playoff Finale")
    assert decision is not None
    assert decision["cut_rule"] == CUT_RULE_NO_CUT
    assert decision["cut_size"] == 0
    assert decision["decision_status"] == "reviewed"
    assert decision["format"] == "72_hole_stroke_play"
    assert decision["rounds"] == 4


def test_resolve_structure_top_n(tmp_path):
    path = tmp_path / "registry.csv"
    write_registry(path, ROWS)
    rows = read_registry(path)
    decision = resolve_structure(rows, 2025, "Test Invitational")
    assert decision is not None
    assert decision["cut_rule"] == CUT_RULE_TOP_N_AND_TIES
    assert decision["cut_size"] == 65


def test_resolve_structure_excluded_or_unknown_returns_none(tmp_path):
    path = tmp_path / "registry.csv"
    write_registry(path, ROWS)
    rows = read_registry(path)
    assert resolve_structure(rows, 2025, "Team Cup") is None
    assert resolve_structure(rows, 2025, "Unknown Event") is None


def test_resolve_structure_unsupported_cut_rule_raises(tmp_path):
    path = tmp_path / "registry.csv"
    bad = [dict(ROWS[0], cut_rule="banana")]
    write_registry(path, bad)
    rows = read_registry(path)
    with pytest.raises(EventRegistryError, match="unsupported cut_rule"):
        resolve_structure(rows, 2025, "Test Invitational")


def test_resolve_structure_unsupported_format_raises(tmp_path):
    path = tmp_path / "registry.csv"
    bad = [dict(ROWS[0], format="match_play")]
    write_registry(path, bad)
    rows = read_registry(path)
    with pytest.raises(EventRegistryError, match="unsupported event structure"):
        resolve_structure(rows, 2025, "Test Invitational")
