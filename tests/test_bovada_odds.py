import csv
import json
from pathlib import Path

import pytest

from golf_props.cli import main
from golf_props.odds import bovada
from golf_props.odds.bovada import (
    BovadaOddsError,
    collect_bovada_golf_odds,
    parse_bovada_payload,
)
from golf_props.schemas import ODDS_SNAPSHOTS_COLUMNS


def sample_payload():
    return [
        {
            "path": [
                {
                    "description": "Rocket Classic",
                    "type": "TOURNAMENT",
                }
            ],
            "events": [
                {
                    "id": "event_1",
                    "description": "Rocket Classic",
                    "link": "/golf/pga-tour/rocket-classic/rocket-classic-202607300800",
                    "status": "O",
                    "startTime": 1785412800000,
                    "displayGroups": [
                        {
                            "markets": [
                                {
                                    "id": "market_winner",
                                    "description": "Winner",
                                    "status": "O",
                                    "outcomes": [
                                        {
                                            "id": "outcome_1",
                                            "description": "Cameron Young",
                                            "price": {"id": "price_1", "american": "+1200"},
                                        }
                                    ],
                                }
                            ]
                        }
                    ],
                },
                {
                    "id": "event_2",
                    "description": "Finishes",
                    "link": "/golf/pga-tour/rocket-classic-finishes/finishes/finishes-202607300801",
                    "status": "O",
                    "startTime": 1785412800000,
                    "displayGroups": [
                        {
                            "markets": [
                                {
                                    "id": "market_top20",
                                    "description": "Top 20 Finish",
                                    "status": "O",
                                    "outcomes": [
                                        {
                                            "id": "outcome_2",
                                            "description": "Akshay Bhatia",
                                            "price": {"id": "price_2", "american": "+350"},
                                        }
                                    ],
                                }
                            ]
                        }
                    ],
                },
                {
                    "id": "event_3",
                    "description": "Jordan Spieth - Make Cut / Miss Cut",
                    "link": "/golf/pga-tour/rocket-classic-specials/cut-lines/jordan-spieth-make-cut-miss-cut",
                    "status": "O",
                    "startTime": 1785412800000,
                    "displayGroups": [
                        {
                            "markets": [
                                {
                                    "id": "market_cut",
                                    "description": "Jordan Spieth",
                                    "status": "O",
                                    "outcomes": [
                                        {
                                            "id": "outcome_3",
                                            "description": "Make",
                                            "price": {"id": "price_3", "american": "-200"},
                                        },
                                        {
                                            "id": "outcome_4",
                                            "description": "Miss",
                                            "price": {"id": "price_4", "american": "+150"},
                                        },
                                    ],
                                }
                            ]
                        }
                    ],
                },
                {
                    "id": "event_4",
                    "description": "1st Round Score - Collin Morikawa",
                    "link": "/golf/pga-championship/1st-round-score-collin-morikawa",
                    "status": "O",
                    "startTime": 1785412800000,
                    "displayGroups": [
                        {
                            "markets": [
                                {
                                    "id": "market_score",
                                    "description": "1st Round Score - Collin Morikawa",
                                    "status": "O",
                                    "outcomes": [
                                        {
                                            "id": "outcome_5",
                                            "description": "Over 69.5",
                                            "price": {"id": "price_5", "american": "-120"},
                                        },
                                        {
                                            "id": "outcome_6",
                                            "description": "Under 69.5",
                                            "price": {"id": "price_6", "american": "-110"},
                                        },
                                    ],
                                }
                            ]
                        }
                    ],
                },
            ],
        }
    ]


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_parse_bovada_payload_maps_core_golf_markets():
    rows = parse_bovada_payload(sample_payload(), captured_at_utc="2026-07-28T18:00:00Z")

    assert [row["market_type"] for row in rows] == ["winner", "top20", "make_cut", "round_score_ou", "round_score_ou"]
    assert rows[0]["player_name"] == "Cameron Young"
    assert rows[2]["player_name"] == "Jordan Spieth"
    assert rows[3]["player_name"] == "Collin Morikawa"
    assert rows[3]["line"] == "69.5"
    assert rows[3]["price_american"] == -120
    assert rows[3]["price_decimal"] == 1.833333


def test_collect_bovada_golf_odds_writes_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(bovada, "fetch_json", lambda url, timeout_seconds: sample_payload())
    output = tmp_path / "odds.csv"
    raw_output = tmp_path / "raw.json"
    report_output = tmp_path / "report.md"

    result = collect_bovada_golf_odds(output, raw_output=raw_output, report_output=report_output)
    rows = read_csv(output)

    assert len(result["rows"]) == 5
    assert len(rows) == 5
    assert raw_output.exists()
    assert "round_score_ou" in report_output.read_text(encoding="utf-8")


def test_cli_collect_bovada_golf_odds(tmp_path, monkeypatch):
    monkeypatch.setattr(bovada, "fetch_json", lambda url, timeout_seconds: sample_payload())
    output = tmp_path / "odds.csv"
    raw_output = tmp_path / "raw.json"
    report_output = tmp_path / "report.md"

    exit_code = main(
        [
            "collect-bovada-golf-odds",
            "--output",
            str(output),
            "--raw-output",
            str(raw_output),
            "--report-output",
            str(report_output),
            "--archive-dir",
            str(tmp_path / "archive"),
            "--weekly-dir",
            str(tmp_path / "weekly"),
        ]
    )

    assert exit_code == 0
    assert output.exists()
    assert raw_output.exists()
    assert report_output.exists()
    assert len(list((tmp_path / "archive").glob("bovada_golf_*.json"))) == 1


# --------------------------------------------------------------------------
# Immutable timestamped snapshots, provider IDs and honest pre_start
# --------------------------------------------------------------------------


def test_parse_bovada_payload_records_provider_ids_without_inventing_join_ids():
    rows = parse_bovada_payload(sample_payload(), captured_at_utc="2026-07-28T18:00:00Z")

    assert rows[0]["event_id"] == "" and rows[0]["player_id"] == ""
    assert rows[0]["provider_event_id"] == "event_1"
    assert rows[0]["provider_market_id"] == "market_winner"
    assert rows[0]["provider_outcome_id"] == "outcome_1"
    assert rows[0]["provider_price_id"] == "price_1"
    assert "canonical" in str(rows[0]["lookup_status"])


def test_timestamped_snapshot_is_immutable_and_keeps_latest_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(bovada, "fetch_json", lambda url, timeout_seconds: sample_payload())
    archive = tmp_path / "archive"
    latest = tmp_path / "latest.csv"

    result = collect_bovada_golf_odds(
        latest,
        raw_output=tmp_path / "latest.json",
        report_output=tmp_path / "report.md",
        archive_dir=archive,
        weekly_dir=tmp_path / "weekly",
    )

    with latest.open(newline="", encoding="utf-8") as handle:
        assert next(csv.reader(handle)) == ODDS_SNAPSHOTS_COLUMNS
    snapshot_json = result["snapshot"]["json_path"]
    snapshot_csv = result["snapshot"]["csv_path"]
    assert snapshot_json.exists() and snapshot_csv.exists()
    payload = json.loads(snapshot_json.read_text(encoding="utf-8"))
    assert payload["schema_version"] == bovada.SNAPSHOT_SCHEMA_VERSION
    assert payload["prices_are_public"] is False
    assert payload["selection_policy"] == "undefined"
    assert payload["row_count"] == len(result["rows"])
    assert payload["rows"][0]["provider_event_id"] == "event_1"
    with snapshot_csv.open(newline="", encoding="utf-8") as handle:
        assert next(csv.reader(handle)) == ODDS_SNAPSHOTS_COLUMNS

    before = snapshot_json.read_bytes()
    with pytest.raises(BovadaOddsError):
        bovada.write_snapshot(
            sample_payload(),
            result["rows"],
            archive,
            result["captured_at_utc"],
        )
    assert snapshot_json.read_bytes() == before


def _event_control(weekly: Path, **overrides):
    weekly.mkdir(parents=True, exist_ok=True)
    record = {
        "event_key": "rocket_classic_2026",
        "event_name": "Rocket Classic",
        "schedule_start_date": "2026-07-30",
        "schedule_end_date": "2026-08-02",
        "competitive_start_date": "2026-07-30",
        "first_tee_at_utc": None,
    }
    record.update(overrides)
    path = weekly / record["event_key"] / "event_control.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    return weekly


def test_pre_start_true_only_with_exact_competitive_start_evidence(tmp_path):
    weekly = _event_control(
        tmp_path / "weekly",
        first_tee_at_utc="2026-07-30T11:00:00Z",
        tee_time_source={"earliest_tee_at_utc": "2026-07-30T11:00:00Z"},
    )
    start = bovada.resolve_competitive_start(weekly, "Rocket Classic")
    assert start["state"] == "known_start"
    assert bovada.resolve_pre_start("2026-07-30T10:00:00Z", start) == (
        True,
        "captured_before_first_tee",
    )
    assert bovada.resolve_pre_start("2026-07-30T12:00:00Z", start) == (
        False,
        "captured_after_first_tee",
    )


def test_schedule_fallback_start_is_date_only_not_pre_start(tmp_path):
    """Bermuda-style fallback: first_tee_at_utc copied from the official date."""
    weekly = _event_control(
        tmp_path / "weekly",
        first_tee_at_utc="2026-07-30T00:00:00-04:00",
        tee_time_source=None,
    )
    start = bovada.resolve_competitive_start(weekly, "Rocket Classic")
    assert start["state"] == "date_only"
    assert bovada.resolve_pre_start("2026-07-30T01:00:00Z", start)[0] is None


def test_date_only_competitive_start_is_unknown_not_assumed_pre_start(tmp_path):
    weekly = _event_control(tmp_path / "weekly")
    start = bovada.resolve_competitive_start(weekly, "Rocket Classic")
    assert start["state"] == "date_only"
    assert bovada.resolve_pre_start("2026-07-30T01:00:00Z", start) == (
        None,
        "event_control.competitive_start_date",
    )


def test_missing_start_evidence_is_unknown(tmp_path):
    start = bovada.resolve_competitive_start(tmp_path / "nowhere", "Rocket Classic")
    assert start["state"] == "unknown"
    assert bovada.resolve_pre_start("2026-07-30T01:00:00Z", start)[0] is None


def test_competitive_start_lookup_uses_shared_formatting_key(tmp_path):
    weekly = _event_control(tmp_path / "weekly", event_name="Cafe\u0301 Open")
    start = bovada.resolve_competitive_start(weekly, "CAFÉ  OPEN")
    assert start["state"] == "date_only"
    assert start["event_key"] == "rocket_classic_2026"
