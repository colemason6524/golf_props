import csv
import json
from pathlib import Path

from golf_props.analysis.history_freshness import assess_history_freshness
from golf_props.schemas import EVENTS_COLUMNS

FIXTURES = Path(__file__).parent / "fixtures"


def _canonical(tmp_path, rows):
    root = tmp_path / "canonical"
    root.mkdir()
    with (root / "events.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENTS_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return root


def _event(**overrides):
    row = {column: "" for column in EVENTS_COLUMNS}
    row.update(
        {
            "event_id": "event_1",
            "source": "cbs_sports",
            "source_event_id": "12345",
            "season": "2025",
            "event_name": "Test Invitational",
            "date_start": "2025-05-01",
            "date_end": "2025-05-04",
        }
    )
    row.update(overrides)
    return row


def _manifest(tmp_path):
    path = tmp_path / "frozen.json"
    path.write_text(
        json.dumps(
            {
                "created_at_utc": "2025-01-01T00:00:00Z",
                "frozen_model": {"source_data_through": "2025-04-30"},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_fresh_when_latest_eligible_event_is_in_active_history(tmp_path):
    result = assess_history_freshness(
        canonical_dir=_canonical(tmp_path, [_event()]),
        schedule_path=FIXTURES / "cbs_schedule_only_one.html",
        as_of_date="2025-05-05",
        frozen_manifest=_manifest(tmp_path),
    )
    assert result["status"] == "fresh"
    assert result["missing_events"] == []
    assert result["missing_immediately_preceding"] is False
    assert result["source_data_through"] == "2025-04-30"
    assert result["latest_completed_eligible_event"]["event_name"] == "Test Invitational"


def test_stale_when_latest_event_is_missing(tmp_path):
    result = assess_history_freshness(
        canonical_dir=_canonical(tmp_path, []),
        schedule_path=FIXTURES / "cbs_schedule_only_one.html",
        as_of_date="2025-05-05",
        frozen_manifest=_manifest(tmp_path),
    )
    assert result["status"] == "stale"
    assert result["missing_immediately_preceding"] is True
    assert [item["event_name"] for item in result["missing_events"]] == [
        "Test Invitational"
    ]


def test_event_on_as_of_date_is_not_treated_as_completed(tmp_path):
    result = assess_history_freshness(
        canonical_dir=_canonical(tmp_path, []),
        schedule_path=FIXTURES / "cbs_schedule_only_one.html",
        as_of_date="2025-05-04",
        frozen_manifest=_manifest(tmp_path),
    )
    assert result["status"] == "unknown"
    assert result["reason"] == "no_completed_eligible_events_in_schedule"


def test_missing_schedule_is_unknown_not_fresh(tmp_path):
    result = assess_history_freshness(
        canonical_dir=_canonical(tmp_path, []),
        schedule_path=tmp_path / "missing.html",
        as_of_date="2025-05-05",
        frozen_manifest=_manifest(tmp_path),
    )
    assert result["status"] == "unknown"
    assert "schedule_missing" in result["reason"]


def test_excluded_team_event_does_not_create_false_staleness(tmp_path):
    schedule = tmp_path / "schedule.html"
    schedule.write_text(
        (FIXTURES / "cbs_schedule_only_one.html")
        .read_text()
        .replace("Test Invitational", "Presidents Cup"),
        encoding="utf-8",
    )
    result = assess_history_freshness(
        canonical_dir=_canonical(tmp_path, []),
        schedule_path=schedule,
        as_of_date="2025-05-05",
        frozen_manifest=_manifest(tmp_path),
    )
    assert result["status"] == "unknown"
    assert [item["event_name"] for item in result["excluded_events"]] == [
        "Presidents Cup"
    ]
