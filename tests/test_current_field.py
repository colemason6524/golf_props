import json
from pathlib import Path

import pytest

from golf_props.ingestion.current_field import (
    FINALITY_FINAL,
    FINALITY_PRELIMINARY,
    SOURCE_KIND_CROSS_CHECK,
    SOURCE_KIND_OFFICIAL,
    CurrentFieldError,
    import_field_evidence,
    load_latest_field_evidence,
)


def write_payload(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_import_official_final_field_evidence(tmp_path):
    payload = write_payload(
        tmp_path / "field.csv",
        [
            "player_name,player_id,entry_status",
            "Scottie Scheffler,,confirmed",
            "Rory McIlroy,,confirmed",
        ],
    )
    evidence = import_field_evidence(
        "test_2025",
        payload,
        source_kind=SOURCE_KIND_OFFICIAL,
        org="official_test",
        url="https://example.com/field",
        captured_at_utc="2025-04-29T00:00:00Z",
        finality=FINALITY_FINAL,
        event_name="Test Invitational",
        expected_field_size=2,
        raw_root=tmp_path / "raw_events",
    )
    assert evidence.ready() is True
    assert len(evidence.rows) == 2
    assert evidence.expected_field_size == 2
    loaded = load_latest_field_evidence(
        "test_2025", raw_root=tmp_path / "raw_events"
    )
    assert loaded is not None
    assert loaded.ready() is True
    assert [row["player_name"] for row in loaded.rows] == [
        "Scottie Scheffler",
        "Rory McIlroy",
    ]


def test_cross_check_or_preliminary_not_ready(tmp_path):
    payload = write_payload(
        tmp_path / "cross.csv",
        ["player_name", "Scottie Scheffler", "Rory McIlroy"],
    )
    cross = import_field_evidence(
        "test_2025",
        payload,
        source_kind=SOURCE_KIND_CROSS_CHECK,
        org="sportsbook_test",
        url="https://example.com/odds",
        captured_at_utc="2025-04-29T00:00:00Z",
        finality=FINALITY_FINAL,
        event_name="Test Invitational",
        raw_root=tmp_path / "raw_events",
    )
    assert cross.ready() is False
    prelim = import_field_evidence(
        "test_2025",
        payload,
        source_kind=SOURCE_KIND_OFFICIAL,
        org="official_test",
        url="https://example.com/field",
        captured_at_utc="2025-04-29T00:00:00Z",
        finality=FINALITY_PRELIMINARY,
        event_name="Test Invitational",
        raw_root=tmp_path / "raw_events",
    )
    assert prelim.ready() is False


def test_load_evidence_uses_adjacent_payload_when_copied_to_another_host(tmp_path):
    payload = write_payload(
        tmp_path / "field.csv",
        ["player_name", "Scottie Scheffler", "Rory McIlroy"],
    )
    raw_root = tmp_path / "raw_events"
    import_field_evidence(
        "test_2025",
        payload,
        source_kind=SOURCE_KIND_OFFICIAL,
        org="official_test",
        url="https://example.com/field",
        captured_at_utc="2025-04-29T00:00:00Z",
        finality=FINALITY_FINAL,
        event_name="Test Invitational",
        raw_root=raw_root,
    )
    manifest_path = raw_root / "test_2025" / "field" / "latest" / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["payload_path"] = "/different-host/field.csv"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    loaded = load_latest_field_evidence("test_2025", raw_root=raw_root)
    assert loaded is not None
    assert len(loaded.rows) == 2


def test_payload_missing_required_column_raises(tmp_path):
    payload = write_payload(tmp_path / "bad.csv", ["foo", "bar"])
    with pytest.raises(CurrentFieldError, match="missing required columns"):
        import_field_evidence(
            "test_2025",
            payload,
            source_kind=SOURCE_KIND_OFFICIAL,
            org="official_test",
            url="https://example.com/field",
            captured_at_utc="2025-04-29T00:00:00Z",
            finality=FINALITY_FINAL,
            event_name="Test Invitational",
            raw_root=tmp_path / "raw_events",
        )


def test_payload_duplicate_name_raises(tmp_path):
    payload = write_payload(
        tmp_path / "dup.csv",
        ["player_name", "Scottie Scheffler", "Scottie Scheffler"],
    )
    with pytest.raises(CurrentFieldError, match="duplicate player_name"):
        import_field_evidence(
            "test_2025",
            payload,
            source_kind=SOURCE_KIND_OFFICIAL,
            org="official_test",
            url="https://example.com/field",
            captured_at_utc="2025-04-29T00:00:00Z",
            finality=FINALITY_FINAL,
            event_name="Test Invitational",
            raw_root=tmp_path / "raw_events",
        )
