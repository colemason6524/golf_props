import csv
from datetime import date
from pathlib import Path

from golf_props.events.structure import read_registry
from golf_props.ingestion.current_event_discovery import (
    discover_upcoming_events,
    select_next_event,
)

FIXTURE = Path(__file__).parent / "fixtures" / "cbs_schedule_upcoming.html"

REGISTRY_ROWS = [
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


def write_registry(path: Path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def discovery():
    return discover_upcoming_events(
        FIXTURE.read_text(encoding="utf-8"), as_of_date=date(2025, 4, 30)
    )


def test_discover_upcoming_filters_to_future_events():
    names = [event["event_name"] for event in discovery()["upcoming_events"]]
    assert names == ["Team Cup", "Test Invitational", "Fall Series Event"]


def test_select_next_event_picks_included_main_event(tmp_path):
    registry = tmp_path / "registry.csv"
    write_registry(registry, REGISTRY_ROWS)
    selected, blockers = select_next_event(discovery(), read_registry(registry))
    assert selected is not None
    assert selected["event_name"] == "Test Invitational"
    assert blockers == []


def test_select_next_event_blocks_when_all_unreviewed(tmp_path):
    registry = tmp_path / "registry.csv"
    registry.write_text(
        "season,source_event_id,event_name,include,format,rounds,cut_rule,cut_size,decision_status,reviewed_at_utc,notes\n",
        encoding="utf-8",
    )
    selected, blockers = select_next_event(discovery(), read_registry(registry))
    assert selected is None
    assert any("unreviewed" in blocker for blocker in blockers)


def test_select_next_event_no_events():
    empty = {"upcoming_events": []}
    selected, blockers = select_next_event(empty, [])
    assert selected is None
    assert blockers == []
