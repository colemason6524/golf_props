from pathlib import Path

import pytest

from golf_props.ingestion.tee_times import (
    TeeTimeError,
    derive_earliest_tee_utc,
    import_tee_time_evidence,
    load_latest_tee_time_evidence,
    parse_tee_time_payload,
)


def write_payload(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_derive_earliest_tee_across_two_holes_dst(tmp_path):
    rows = parse_tee_time_payload(
        write_payload(
            tmp_path / "tee1.csv",
            [
                "player_name,local_tee_datetime,starting_hole",
                "Scottie Scheffler,2025-05-01 07:12,1",
                "Rory McIlroy,2025-05-01 07:00,10",
            ],
        )
    )
    earliest, count = derive_earliest_tee_utc(rows, "America/New_York")
    assert earliest == "2025-05-01T11:00:00Z"
    assert count == 2


def test_derive_earliest_respects_timezone_offset(tmp_path):
    rows = parse_tee_time_payload(
        write_payload(
            tmp_path / "tee2.csv",
            [
                "player_name,local_tee_datetime,starting_hole",
                "Scottie Scheffler,2025-11-01 09:00,1",
            ],
        )
    )
    earliest, _ = derive_earliest_tee_utc(rows, "America/Los_Angeles")
    assert earliest == "2025-11-01T16:00:00Z"


def test_unknown_timezone_raises():
    with pytest.raises(TeeTimeError, match="unknown IANA timezone"):
        derive_earliest_tee_utc(
            [{"player_name": "X", "local_tee_datetime": "2025-05-01 07:00"}],
            "Not/AZone",
        )


def test_malformed_time_raises():
    with pytest.raises(TeeTimeError, match="unparseable local tee time"):
        derive_earliest_tee_utc(
            [{"player_name": "X", "local_tee_datetime": "2025-05-01"}],
            "America/New_York",
        )


def test_import_tee_time_evidence_round_trip(tmp_path):
    payload = write_payload(
        tmp_path / "tee.csv",
        [
            "player_name,local_tee_datetime,starting_hole",
            "Scottie Scheffler,2025-05-01 07:12,1",
            "Rory McIlroy,2025-05-01 07:00,10",
        ],
    )
    evidence = import_tee_time_evidence(
        "test_2025",
        "Test Invitational",
        payload,
        org="official_test",
        url="https://example.com/teetimes",
        captured_at_utc="2025-04-30T00:00:00Z",
        local_timezone="America/New_York",
        reviewed_by="operator",
        raw_root=tmp_path / "raw_events",
    )
    assert evidence.earliest_tee_at_utc == "2025-05-01T11:00:00Z"
    loaded = load_latest_tee_time_evidence(
        "test_2025", raw_root=tmp_path / "raw_events"
    )
    assert loaded is not None
    assert loaded.earliest_tee_at_utc == evidence.earliest_tee_at_utc
    assert loaded.reviewed_by == "operator"
