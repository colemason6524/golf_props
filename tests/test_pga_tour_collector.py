"""Tests for the automated PGA TOUR field and tee-time collector."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from golf_props.ingestion.pga_tour_collector import (
    PGATourCollectorError,
    CollectedField,
    CollectedTeeTimes,
    _event_name_to_slug,
    _extract_next_data,
    _parse_player,
    _parse_tee_times_from_html,
    _convert_utc_time_to_local,
    collect_pga_tour_field,
    collect_pga_tour_tee_times,
    persist_field_evidence,
    persist_tee_time_evidence,
    write_field_csv,
    write_tee_times_csv,
)
from golf_props.ingestion.current_field import load_latest_field_evidence
from golf_props.ingestion.tee_times import load_latest_tee_time_evidence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_NEXT_DATA_FIELD = {
    "props": {
        "pageProps": {
            "dehydratedState": {
                "queries": [
                    {
                        "queryKey": ["field", {"tournamentId": "R2026557", "changesOnly": False}],
                        "state": {
                            "data": {
                                "tournamentName": "Biltmore Championship Asheville",
                                "id": "R2026557",
                                "players": [
                                    {
                                        "id": "29",
                                        "firstName": "Jacob",
                                        "lastName": "Bridgeman",
                                        "displayName": "Bridgeman, Jacob",
                                        "amateur": False,
                                        "country": "United States",
                                        "countryFlag": "USA",
                                        "withdrawn": False,
                                        "status": "IN",
                                        "owgr": "29",
                                    },
                                    {
                                        "id": "48001",
                                        "firstName": "Zach",
                                        "lastName": "Bauchou",
                                        "displayName": "Bauchou, Zach",
                                        "amateur": False,
                                        "country": "United States",
                                        "countryFlag": "USA",
                                        "withdrawn": False,
                                        "status": "IN",
                                        "owgr": "155",
                                    },
                                    {
                                        "id": "70106",
                                        "firstName": "Carson",
                                        "lastName": "Bertagnole",
                                        "displayName": "Bertagnole, Carson",
                                        "amateur": True,
                                        "country": "United States",
                                        "countryFlag": "USA",
                                        "withdrawn": False,
                                        "status": "IN",
                                        "owgr": None,
                                    },
                                ],
                                "alternates": [
                                    {
                                        "id": "99999",
                                        "firstName": "Bill",
                                        "lastName": "Haas",
                                        "displayName": "Haas, Bill",
                                        "amateur": False,
                                        "withdrawn": False,
                                        "status": "ALT",
                                    },
                                ],
                            }
                        },
                    }
                ]
            }
        }
    }
}

SAMPLE_NEXT_DATA_TEE_TIMES = {
    "props": {
        "pageProps": {
            "dehydratedState": {
                "queries": [
                    {
                        "queryKey": ["leaderboard", {"leaderboardId": "R2026557"}],
                        "state": {
                            "data": {
                                "tournamentId": "R2026557",
                                "timezone": "America/New_York",
                                "leaderboard": [],
                            }
                        },
                    }
                ]
            }
        }
    }
}

SAMPLE_TEE_TIMES_HTML = """
<html><body>
<div>1:30 PM UTC | 1 | Tommy Fleetwood / Brian Harman | -</div>
<div>1:40 PM UTC | 1 | Daniel Bennett / Chris Kirk | -</div>
<div>1:50 PM UTC | 1 | Max Greyserman / Nick Taylor | -</div>
<div>2:00 PM UTC | 10 | Hideki Matsuyama / Keith Mitchell | -</div>
</body></html>
"""


# ---------------------------------------------------------------------------
# Unit tests: URL slug conversion
# ---------------------------------------------------------------------------

class TestEventNameToSlug:
    def test_simple_name(self):
        assert _event_name_to_slug("TOUR Championship") == "tour-championship"

    def test_name_with_special_chars(self):
        assert _event_name_to_slug("Arnold Palmer Invitational presented by Mastercard") == \
            "arnold-palmer-invitational-presented-by-mastercard"

    def test_name_with_accented_chars(self):
        slug = _event_name_to_slug("Biltmore Championship Asheville")
        assert slug == "biltmore-championship-asheville"

    def test_multiple_spaces(self):
        assert _event_name_to_slug("Event  With   Spaces") == "event-with-spaces"


# ---------------------------------------------------------------------------
# Unit tests: __NEXT_DATA__ extraction
# ---------------------------------------------------------------------------

class TestExtractNextData:
    def test_extracts_json(self):
        html = '<html><script id="__NEXT_DATA__" type="application/json">{"foo": "bar"}</script></html>'
        result = _extract_next_data(html)
        assert result == {"foo": "bar"}

    def test_raises_on_missing(self):
        with pytest.raises(PGATourCollectorError, match="no __NEXT_DATA__"):
            _extract_next_data("<html><body>no data</body></html>")

    def test_raises_on_invalid_json(self):
        with pytest.raises(PGATourCollectorError, match="invalid __NEXT_DATA__"):
            _extract_next_data('<script id="__NEXT_DATA__" type="application/json">{bad json}</script>')


# ---------------------------------------------------------------------------
# Unit tests: Player parsing
# ---------------------------------------------------------------------------

class TestParsePlayer:
    def test_field_query_format(self):
        entry = {
            "id": "29",
            "firstName": "Jacob",
            "lastName": "Bridgeman",
            "displayName": "Bridgeman, Jacob",
            "amateur": False,
            "withdrawn": False,
            "status": "IN",
        }
        result = _parse_player(entry)
        assert result is not None
        assert result["player_name"] == "Bridgeman, Jacob"
        assert result["player_id"] == "29"
        assert result["entry_status"] == "confirmed"

    def test_amateur_player(self):
        entry = {
            "id": "70106",
            "firstName": "Carson",
            "lastName": "Bertagnole",
            "displayName": "Bertagnole, Carson",
            "amateur": True,
            "withdrawn": False,
            "status": "IN",
        }
        result = _parse_player(entry)
        assert result is not None
        assert "(a)" in result["player_name"]

    def test_withdrawn_player(self):
        entry = {
            "id": "12345",
            "firstName": "Test",
            "lastName": "Player",
            "displayName": "Player, Test",
            "amateur": False,
            "withdrawn": True,
            "status": "IN",
        }
        result = _parse_player(entry)
        assert result is not None
        assert result["entry_status"] == "withdrawn"

    def test_tcotr_format(self):
        entry = {
            "playerId": "60004",
            "playerName": "Jacob Bridgeman",
        }
        result = _parse_player(entry)
        assert result is not None
        assert result["player_name"] == "Jacob Bridgeman"
        assert result["player_id"] == "60004"

    def test_leaderboard_format(self):
        entry = {
            "player": {
                "id": "51977",
                "firstName": "Max",
                "lastName": "Greyserman",
                "displayName": "Max Greyserman",
            }
        }
        result = _parse_player(entry)
        assert result is not None
        assert result["player_name"] == "Max Greyserman"
        assert result["player_id"] == "51977"

    def test_unknown_format_returns_none(self):
        result = _parse_player({"unknown": "format"})
        assert result is None


# ---------------------------------------------------------------------------
# Unit tests: Tee time parsing
# ---------------------------------------------------------------------------

class TestParseTeeTimesFromHtml:
    def test_parses_utc_tee_times(self):
        rows = _parse_tee_times_from_html(SAMPLE_TEE_TIMES_HTML)
        # 4 groups of 2 players each = 8 rows
        assert len(rows) == 8
        assert rows[0]["starting_hole"] == "1"
        assert "Tommy Fleetwood" in rows[0]["player_name"]
        assert "Brian Harman" in rows[1]["player_name"]

    def test_empty_html_returns_empty(self):
        rows = _parse_tee_times_from_html("<html><body>no tee times</body></html>")
        assert rows == []


class TestConvertUtcTimeToLocal:
    def test_standard_conversion(self):
        result = _convert_utc_time_to_local("1:30 PM UTC")
        assert result == "1900-01-01 13:30"

    def test_midnight(self):
        result = _convert_utc_time_to_local("12:00 AM UTC")
        assert result == "1900-01-01 00:00"


# ---------------------------------------------------------------------------
# Unit tests: CSV writing
# ---------------------------------------------------------------------------

class TestWriteFieldCsv:
    def test_writes_correct_format(self, tmp_path):
        path = tmp_path / "field.csv"
        players = [
            {"player_name": "Scottie Scheffler", "player_id": "34046", "entry_status": "confirmed"},
            {"player_name": "Rory McIlroy", "player_id": "28237", "entry_status": "confirmed"},
        ]
        write_field_csv(path, players)
        content = path.read_text(encoding="utf-8")
        assert "player_id,player_name,entry_status" in content
        assert "34046,Scottie Scheffler,confirmed" in content
        assert "28237,Rory McIlroy,confirmed" in content

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "field.csv"
        write_field_csv(path, [{"player_name": "Test", "player_id": "1", "entry_status": "confirmed"}])
        assert path.exists()


class TestWriteTeeTimesCsv:
    def test_writes_correct_format(self, tmp_path):
        path = tmp_path / "tee.csv"
        rows = [
            {"player_name": "Scottie Scheffler", "local_tee_datetime": "2026-09-17 13:30", "starting_hole": "1"},
        ]
        write_tee_times_csv(path, rows, "2026-09-17T17:30:00Z")
        content = path.read_text(encoding="utf-8")
        assert "player_name,local_tee_datetime,starting_hole" in content
        assert "Scottie Scheffler,2026-09-17 13:30,1" in content


# ---------------------------------------------------------------------------
# Integration tests: Persist evidence
# ---------------------------------------------------------------------------

class TestPersistFieldEvidence:
    def test_persists_and_loads(self, tmp_path):
        collected = CollectedField(
            event_key="test_event_2026",
            event_name="Test Event",
            tournament_id="R2026999",
            url="https://www.pgatour.com/tournaments/2026/test-event/R2026999/field",
            captured_at_utc="2026-09-17T12:00:00Z",
            raw_html_path="/tmp/test.html",
            raw_html_sha256="abc123",
            players=[
                {"player_name": "Scottie Scheffler", "player_id": "34046", "entry_status": "confirmed"},
                {"player_name": "Rory McIlroy", "player_id": "28237", "entry_status": "confirmed"},
            ],
            field_size=2,
        )
        raw_root = tmp_path / "raw_events"
        evidence = persist_field_evidence(collected, raw_events_root=raw_root)

        assert evidence.ready() is True
        assert len(evidence.rows) == 2
        assert evidence.source_kind == "official"
        assert evidence.org == "pga_tour"

        # Verify it can be loaded back
        loaded = load_latest_field_evidence("test_event_2026", raw_root=raw_root)
        assert loaded is not None
        assert loaded.ready() is True
        assert len(loaded.rows) == 2

        # Verify evidence directory structure
        evidence_dir = raw_root / "test_event_2026" / "field" / "latest"
        assert evidence_dir.exists()
        assert (evidence_dir / "source_manifest.json").exists()
        assert (evidence_dir / "field.csv").exists()


class TestPersistTeeTimeEvidence:
    def test_persists_and_loads(self, tmp_path):
        collected = CollectedTeeTimes(
            event_key="test_event_2026",
            event_name="Test Event",
            tournament_id="R2026999",
            url="https://www.pgatour.com/tournaments/2026/test-event/R2026999/tee-times",
            captured_at_utc="2026-09-17T12:00:00Z",
            raw_html_path="/tmp/test.html",
            raw_html_sha256="abc123",
            local_timezone="America/New_York",
            rows=[
                {"player_name": "Scottie Scheffler", "local_tee_datetime": "2026-09-17 13:30", "starting_hole": "1"},
            ],
            earliest_tee_at_utc="2026-09-17T17:30:00Z",
        )
        raw_root = tmp_path / "raw_events"
        evidence = persist_tee_time_evidence(collected, raw_events_root=raw_root)

        assert evidence.earliest_tee_at_utc == "2026-09-17T17:30:00Z"
        assert len(evidence.rows) == 1

        # Verify evidence directory structure
        evidence_dir = raw_root / "test_event_2026" / "tee_times" / "latest"
        assert evidence_dir.exists()
        assert (evidence_dir / "source_manifest.json").exists()
        assert (evidence_dir / "tee_times.csv").exists()

        # Verify it can be loaded back
        loaded = load_latest_tee_time_evidence("test_event_2026", raw_root=raw_root)
        assert loaded is not None
        assert loaded.earliest_tee_at_utc == "2026-09-17T17:30:00Z"


# ---------------------------------------------------------------------------
# Integration tests: Automated collection (mocked HTTP)
# ---------------------------------------------------------------------------

class TestCollectPgaTourField:
    @patch("golf_props.ingestion.pga_tour_collector.fetch_page")
    def test_collects_field_from_pga_tour(self, mock_fetch, tmp_path):
        # Build a mock HTML page with __NEXT_DATA__
        mock_html = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(SAMPLE_NEXT_DATA_FIELD)}</script></html>'
        mock_fetch.return_value = (200, mock_html)

        collected = collect_pga_tour_field(
            event_key="biltmore_championship_asheville_2026",
            event_name="Biltmore Championship Asheville",
            tournament_id="R2026557",
            season=2026,
            raw_events_root=tmp_path / "raw_events",
        )

        assert collected.tournament_id == "R2026557"
        assert collected.field_size == 3
        assert len(collected.players) == 3
        assert collected.players[0]["player_id"] == "29"
        assert collected.players[2]["entry_status"] == "confirmed"  # amateur is still confirmed

    @patch("golf_props.ingestion.pga_tour_collector.fetch_page")
    def test_raises_on_http_error(self, mock_fetch, tmp_path):
        mock_fetch.return_value = (404, "not found")
        with pytest.raises(PGATourCollectorError, match="status 404"):
            collect_pga_tour_field(
                event_key="test",
                event_name="Test",
                tournament_id="R123",
                season=2026,
                raw_events_root=tmp_path / "raw_events",
            )

    @patch("golf_props.ingestion.pga_tour_collector.fetch_page")
    def test_raises_on_no_players(self, mock_fetch, tmp_path):
        empty_data = {
            "props": {
                "pageProps": {
                    "dehydratedState": {
                        "queries": [
                            {
                                "queryKey": ["field", {"tournamentId": "R123"}],
                                "state": {"data": {"id": "R123", "players": []}},
                            }
                        ]
                    }
                }
            }
        }
        mock_html = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(empty_data)}</script></html>'
        mock_fetch.return_value = (200, mock_html)

        with pytest.raises(PGATourCollectorError, match="no players extracted"):
            collect_pga_tour_field(
                event_key="test",
                event_name="Test",
                tournament_id="R123",
                season=2026,
                raw_events_root=tmp_path / "raw_events",
            )


class TestCollectPgaTourTeeTimes:
    @patch("golf_props.ingestion.pga_tour_collector.fetch_page")
    def test_collects_tee_times(self, mock_fetch, tmp_path):
        mock_html = f"""<html>
        <script id="__NEXT_DATA__" type="application/json">{json.dumps(SAMPLE_NEXT_DATA_TEE_TIMES)}</script>
        <body>{SAMPLE_TEE_TIMES_HTML}</body>
        </html>"""
        mock_fetch.return_value = (200, mock_html)

        collected = collect_pga_tour_tee_times(
            event_key="test_event_2026",
            event_name="Test Event",
            tournament_id="R2026557",
            season=2026,
            raw_events_root=tmp_path / "raw_events",
        )

        assert collected is not None
        assert len(collected.rows) >= 4
        assert collected.earliest_tee_at_utc != ""

    @patch("golf_props.ingestion.pga_tour_collector.fetch_page")
    def test_returns_empty_when_no_tee_times(self, mock_fetch, tmp_path):
        mock_html = "<html><body>no tee times yet</body></html>"
        mock_fetch.return_value = (200, mock_html)

        collected = collect_pga_tour_tee_times(
            event_key="test_event_2026",
            event_name="Test Event",
            tournament_id="R2026557",
            season=2026,
            raw_events_root=tmp_path / "raw_events",
        )

        assert collected is not None
        assert collected.rows == []
        assert collected.earliest_tee_at_utc == ""


# ---------------------------------------------------------------------------
# Test parse_display_date_start
# ---------------------------------------------------------------------------


class TestParseDisplayDateStart:
    def test_standard_date(self):
        from golf_props.ingestion.pga_tour_collector import parse_display_date_start
        result = parse_display_date_start("Sep 17 - 20, 2026", 2026)
        assert result == "2026-09-17"

    def test_january_date(self):
        from golf_props.ingestion.pga_tour_collector import parse_display_date_start
        result = parse_display_date_start("January 15 - 18, 2026", 2026)
        assert result == "2026-01-15"

    def test_single_digit_day(self):
        from golf_props.ingestion.pga_tour_collector import parse_display_date_start
        result = parse_display_date_start("Jun 5 - 8, 2025", 2025)
        assert result == "2025-06-05"

    def test_empty_string_returns_none(self):
        from golf_props.ingestion.pga_tour_collector import parse_display_date_start
        result = parse_display_date_start("", 2026)
        assert result is None

    def test_invalid_format_returns_none(self):
        from golf_props.ingestion.pga_tour_collector import parse_display_date_start
        result = parse_display_date_start("2026-09-17 to 2026-09-20", 2026)
        assert result is None
