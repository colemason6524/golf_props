"""Real sportsbook prices on a forecast board: strict joins, honest labels."""

import csv
import hashlib
import json
from pathlib import Path

import pytest

from golf_props.odds import board_prices as bp

FIXTURES = Path(__file__).parent / "fixtures" / "odds"
SNAPSHOT = FIXTURES / "bovada_golf_20261026T125600Z_excerpt.json"
POST_START = FIXTURES / "bovada_golf_20261030T180000Z_poststart.json"
TWO_EVENTS = FIXTURES / "bovada_golf_20261026T125600Z_two_events.json"
ALIASES = FIXTURES / "odds_event_aliases.csv"
PLAYERS = FIXTURES / "players.csv"
PLAYER_ALIASES = FIXTURES / "player_aliases.csv"


def _rows(*names):
    return [
        {
            "rank": index,
            "player_name": name,
            "winner_prob": 0.1,
            "top5_prob": 0.3,
            "top10_prob": 0.5,
            "top20_prob": 0.7,
            "make_cut_prob": 0.9,
        }
        for index, name in enumerate(names, 1)
    ]


def _annotate(rows, **overrides):
    kwargs = {
        "event_name": "Mexico Open",
        "event_key": "mexico_open_2026",
        "event_date": "2026-10-29",
        "rows": rows,
        "odds_snapshot": SNAPSHOT,
        "odds_archive_dir": None,
        "odds_latest_csv": None,
        "weekly_dir": None,
        "event_aliases_path": ALIASES,
        "player_aliases_path": PLAYER_ALIASES,
        "players_table": PLAYERS,
    }
    kwargs.update(overrides)
    return bp.annotate_board_rows(**kwargs)


def test_same_event_quote_is_attached_with_provenance():
    rows, odds = _annotate(_rows("Player A", "Player B"))

    assert odds["status"] == "priced"
    price = rows[0]["price"]
    assert price["sportsbook"] == "Bovada"
    assert price["market"] == "winner"
    assert price["price_american"] == 1100
    assert price["price_decimal"] == 12.0
    assert price["captured_at_utc"] == "2026-10-26T12:56:00.947497Z"
    assert price["pre_start"] is True
    assert price["pre_event_price"] is True
    assert price["prospective_roi_eligible"] is False
    assert price["provenance"]["provider_event_id"] == "prov-ev-1"
    assert price["provenance"]["provider_price_id"] == "prov-pr-a"
    assert price["provenance"]["event_match"] == "exact"
    assert odds["event_identity"]["provider_event_name"] == "Mexico Open"
    assert odds["pre_start"] is True
    assert odds["usable_as_pre_event_price"] is True
    assert odds["readiness"]["state"] == "ready"
    assert odds["priced_players"] == 2
    assert odds["placement_market_prices"] == "unavailable"
    assert "top-5" in odds["placement_statement"]


def test_player_alias_join_uses_the_canonical_players_table():
    rows, odds = _annotate(_rows("Alias Player", "Player A"))
    assert odds["status"] == "priced"
    assert rows[0]["price"]["price_american"] == 2500
    assert rows[0]["price"]["price_decimal"] == 26.0


def test_alias_event_join_requires_the_reviewed_row():
    rows = _rows("Player A", "Player B")
    priced, odds = _annotate(rows, event_name="VidantaWorld Mexico Open",
                             event_key="vidantaworld_mexico_open_2026")
    assert odds["status"] == "priced"
    assert odds["event_identity"]["match"] == "alias"
    assert odds["event_identity"]["alias"]["provider_event_start_date"] == "2026-10-29"
    assert priced[0]["price"]["provenance"]["event_match"] == "alias"

    _, unpriced = _annotate(
        _rows("Player A"),
        event_name="VidantaWorld Mexico Open",
        event_key="vidantaworld_mexico_open_2026",
        event_aliases_path=FIXTURES / "no_such_aliases.csv",
    )
    assert unpriced["status"] == "unpriced"
    assert unpriced["reason"] == "no_matching_event_snapshot"


def test_other_events_prices_never_attach():
    rows, odds = _annotate(
        _rows("Player A", "Player B"),
        event_name="Butterfield Bermuda Championship",
        event_key="butterfield_bermuda_championship_2026",
        event_date="2026-10-22",
    )
    assert odds["status"] == "unpriced"
    assert odds["reason"] == "no_matching_event_snapshot"
    assert all(row["price"] is None for row in rows)


def test_two_provider_events_are_ambiguous_and_stay_unpriced():
    rows, odds = _annotate(
        _rows("Player A"),
        event_name="VidantaWorld Mexico Open",
        event_key="vidantaworld_mexico_open_2026",
        odds_snapshot=TWO_EVENTS,
    )
    assert odds["status"] == "unpriced"
    assert odds["reason"] == "ambiguous_event"
    assert rows[0]["price"] is None


def test_ambiguous_player_quotes_stay_unpriced():
    rows, odds = _annotate(_rows("Twin Price", "Player A"))
    assert rows[0]["price"] is None
    assert rows[1]["price"]["price_american"] == 1100
    assert odds["unpriced_reasons"]["ambiguous_player"] == 1
    assert odds["priced_players"] == 1


def test_post_start_quote_is_never_a_pre_event_price():
    rows, odds = _annotate(_rows("Player A"), odds_snapshot=POST_START)
    assert odds["status"] == "unpriced"
    assert odds["pre_start"] is False
    assert rows[0]["price"] is None
    assert odds["unpriced_reasons"]["captured_after_start"] == 1


def test_same_day_date_only_start_cannot_assert_pre_start(tmp_path):
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    data["captured_at_utc"] = "2026-10-29T10:00:00Z"
    for row in data["rows"]:
        row["captured_at_utc"] = "2026-10-29T10:00:00Z"
    same_day = tmp_path / "bovada_golf_20261029T100000Z.json"
    same_day.write_text(json.dumps(data), encoding="utf-8")

    rows, odds = _annotate(_rows("Player A"), odds_snapshot=same_day)
    assert odds["pre_start"] is None
    assert odds["pre_start_basis"] == "same_day_date_only_competitive_start_unknown"
    assert odds["usable_as_pre_event_price"] is False
    assert rows[0]["price"] is None
    assert odds["unpriced_reasons"]["capture_time_unproven_pre_start"] == 1


def test_known_exact_start_decides_by_instant(tmp_path):
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    data["competitive_start"]["Mexico Open"] = {
        "state": "known_start",
        "start_at_utc": "2026-10-26T18:00:00Z",
    }
    exact = tmp_path / "bovada_golf_20261026T125600Z.json"
    exact.write_text(json.dumps(data), encoding="utf-8")
    rows, odds = _annotate(_rows("Player A"), odds_snapshot=exact)
    assert odds["pre_start"] is True and rows[0]["price"] is not None

    data["competitive_start"]["Mexico Open"]["start_at_utc"] = "2026-10-26T09:00:00Z"
    late = tmp_path / "bovada_golf_20261026T125601Z.json"
    late.write_text(json.dumps(data), encoding="utf-8")
    late_rows, late_odds = _annotate(_rows("Player A"), odds_snapshot=late)
    assert late_odds["pre_start"] is False
    assert late_rows[0]["price"] is None


def test_only_the_winner_market_is_used_for_any_price():
    rows, odds = _annotate(_rows("Top 20 Only", "Player A"))
    assert rows[0]["price"] is None
    assert odds["unpriced_reasons"]["no_quote_for_player"] == 1
    assert odds["market"] == "winner"
    assert "no top-5, top-10 or top-20 prices" in odds["placement_statement"]
    assert odds["placement_market_prices"] == "unavailable"


def test_model_probability_is_never_used_as_a_price():
    rows, _ = _annotate(_rows("Player A"))
    price = rows[0]["price"]
    assert price["implied_probability"] == pytest.approx(0.083333)
    assert rows[0]["winner_prob"] == 0.1
    assert "winner_prob" not in price
    assert price["price_american"] == 1100


def test_latest_csv_is_a_read_only_source_with_a_fingerprint(tmp_path):
    csv_path = tmp_path / "bovada_golf_latest.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "odds_id",
                "event_name",
                "player_name",
                "sportsbook",
                "market_type",
                "market_name",
                "price_american",
                "price_decimal",
                "implied_probability",
                "captured_at_utc",
                "source_url",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "odds_id": "odds_csv_1",
                "event_name": "Mexico Open",
                "player_name": "Player A",
                "sportsbook": "Bovada",
                "market_type": "winner",
                "market_name": "Winner",
                "price_american": 1100,
                "price_decimal": 12.0,
                "implied_probability": 0.083333,
                "captured_at_utc": "2026-10-26T12:56:00Z",
                "source_url": "https://www.bovada.lv/golf/pga-tour/mexico-open",
            }
        )
    before = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    weekly = tmp_path / "weekly" / "mexico_open_2026"
    weekly.mkdir(parents=True)
    (weekly / "event_control.json").write_text(
        json.dumps(
            {
                "event_key": "mexico_open_2026",
                "event_name": "Mexico Open",
                "competitive_start_date": "2026-10-29",
            }
        ),
        encoding="utf-8",
    )
    rows, odds = _annotate(
        _rows("Player A"),
        odds_snapshot=None,
        odds_latest_csv=csv_path,
        weekly_dir=tmp_path / "weekly",
    )
    assert odds["status"] == "priced"
    assert odds["source"]["kind"] == "latest_csv"
    assert odds["source"]["sha256"] == before
    assert rows[0]["price"]["source"]["sha256"] == before
    assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == before


def test_archive_prefers_a_pre_start_capture_over_a_later_one(tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / POST_START.name).write_text(POST_START.read_text(encoding="utf-8"))
    (archive / SNAPSHOT.name).write_text(SNAPSHOT.read_text(encoding="utf-8"))
    rows, odds = _annotate(
        _rows("Player A", "Player B"),
        odds_snapshot=None,
        odds_archive_dir=archive,
    )
    assert odds["status"] == "priced"
    assert odds["pre_start"] is True
    assert odds["capture_utc"] == "2026-10-26T12:56:00.947497Z"
    assert rows[0]["price"]["price_american"] == 1100


def test_capture_from_another_season_never_joins(tmp_path):
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    for row in data["rows"]:
        row["season"] = "2025"
    other_season = tmp_path / "bovada_golf_20251026T125600Z.json"
    other_season.write_text(json.dumps(data), encoding="utf-8")
    rows, odds = _annotate(_rows("Player A"), odds_snapshot=other_season)
    assert odds["status"] == "unpriced"
    assert odds["reason"] == "no_matching_event_snapshot"
    assert rows[0]["price"] is None


def test_unknown_snapshot_start_falls_back_to_canonical_event_control(tmp_path):
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    data["competitive_start"] = {
        "Mexico Open": {"state": "unknown", "source": "no_matching_event_control"}
    }
    snapshot = tmp_path / "bovada_golf_20261026T125600Z_unknown_start.json"
    snapshot.write_text(json.dumps(data), encoding="utf-8")
    weekly = tmp_path / "weekly" / "vidantaworld_mexico_open_2026"
    weekly.mkdir(parents=True)
    (weekly / "event_control.json").write_text(
        json.dumps(
            {
                "event_key": "vidantaworld_mexico_open_2026",
                "event_name": "VidantaWorld Mexico Open",
                "competitive_start_date": "2026-10-29",
            }
        ),
        encoding="utf-8",
    )
    rows, odds = _annotate(
        _rows("Player A"),
        event_name="VidantaWorld Mexico Open",
        event_key="vidantaworld_mexico_open_2026",
        odds_snapshot=snapshot,
        weekly_dir=tmp_path / "weekly",
    )
    assert odds["pre_start"] is True
    assert rows[0]["price"] is not None


def test_snapshot_is_never_rewritten_by_annotation():
    before = hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest()
    _annotate(_rows("Player A", "Player B"))
    assert hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest() == before


def _market_snapshot(tmp_path, market_rows):
    """One preserved capture carrying whatever markets the test declares."""
    base = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    template = dict(base["rows"][0])
    rows = []
    for index, (name, market, american, market_name) in enumerate(market_rows):
        row = dict(template)
        row.update(
            {
                "odds_id": f"odds_market_{index}",
                "player_name": name,
                "selection_name": name,
                "market_type": market,
                "market_name": market_name,
                "price_american": american,
                "price_decimal": round(1 + american / 100, 3)
                if american > 0
                else round(1 + 100 / abs(american), 3),
                "implied_probability": 0.0,
            }
        )
        rows.append(row)
    base["rows"] = rows
    base["market_counts"] = {}
    base["row_count"] = len(rows)
    path = tmp_path / "bovada_golf_20261026T125600Z_markets.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    return path


def test_placement_markets_attach_separately_from_the_winner_market(tmp_path):
    snapshot = _market_snapshot(
        tmp_path,
        [
            ("Player A", "winner", 1100, "Winner"),
            ("Player A", "top5", 450, "Top 5"),
            ("Player A", "top10", 210, "Top 10"),
            ("Player A", "top20", 105, "Top 20"),
            ("Player B", "winner", 1800, "Winner"),
            ("Player B", "top20", 260, "Top 20"),
        ],
    )
    rows, odds = _annotate(_rows("Player A", "Player B"), odds_snapshot=snapshot)
    assert rows[0]["price"]["market"] == "winner"
    assert rows[0]["prices"]["top5"]["price_american"] == 450
    assert rows[0]["prices"]["top10"]["price_american"] == 210
    assert rows[0]["prices"]["top20"]["price_american"] == 105
    assert rows[1]["price"]["market"] == "winner"
    assert rows[1]["prices"]["top5"] is None
    assert rows[1]["prices"]["top20"]["price_american"] == 260
    assert odds["placement_market_prices"] == "attached"
    coverage = odds["market_coverage"]
    assert coverage["winner"]["priced_players"] == 2
    assert coverage["top5"]["priced_players"] == 1
    assert coverage["top10"]["priced_players"] == 1
    assert coverage["top20"]["priced_players"] == 2
    assert coverage["top5"]["unpriced_reasons"]["no_quote_for_player"] == 1
    assert "Top 5 1/2" in odds["placement_statement"]
    assert "dead-heat" in odds["placement_statement"]
    assert odds["settlement_semantics"]["prospective_roi"] == "unavailable"
    assert odds["prospective_roi"] == "unavailable"


def test_placement_only_player_is_priced_for_placement_not_winner(tmp_path):
    snapshot = _market_snapshot(
        tmp_path,
        [
            ("Player A", "winner", 1100, "Winner"),
            ("Placement Only", "top10", 500, "Top 10"),
        ],
    )
    rows, odds = _annotate(_rows("Player A", "Placement Only"), odds_snapshot=snapshot)
    assert rows[1]["price"] is None
    assert rows[1]["prices"]["top10"]["price_american"] == 500
    assert odds["priced_players"] == 1
    assert odds["any_market_priced_players"] == 2


def test_ambiguous_placement_quote_stays_unpriced_without_affecting_winner(tmp_path):
    snapshot = _market_snapshot(
        tmp_path,
        [
            ("Player A", "winner", 1100, "Winner"),
            ("Player A", "top5", 450, "Top 5"),
            ("Player A", "top5", 460, "Top 5"),
        ],
    )
    rows, odds = _annotate(_rows("Player A"), odds_snapshot=snapshot)
    assert rows[0]["price"]["price_american"] == 1100
    assert rows[0]["prices"]["top5"] is None
    coverage = odds["market_coverage"]
    assert coverage["winner"]["priced_players"] == 1
    assert coverage["top5"]["priced_players"] == 0
    assert coverage["top5"]["unpriced_reasons"]["ambiguous_player"] == 1


def test_post_start_capture_never_prices_any_market():
    rows, odds = _annotate(_rows("Player A"), odds_snapshot=POST_START)
    assert odds["status"] == "unpriced"
    assert odds["placement_market_prices"] == "unavailable"
    assert all(value is None for row in rows for value in row["prices"].values())
    assert odds["settlement_semantics"]["grading_target"] == (
        "finish_position_le_n_all_ties_count"
    )


def test_placement_price_never_derives_from_the_model_probability(tmp_path):
    snapshot = _market_snapshot(
        tmp_path,
        [("Player A", "top20", 105, "Top 20")],
    )
    rows, _ = _annotate(_rows("Player A"), odds_snapshot=snapshot)
    price = rows[0]["prices"]["top20"]
    assert price["price_american"] == 105
    assert price["prospective_roi_eligible"] is False
    assert price["settlement"] == "book_specific_not_modelled_no_roi"
    assert rows[0]["top20_prob"] == 0.7
    assert "top20_prob" not in price


def _initialism_snapshot(tmp_path, *, start="2026-11-05", names=None):
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    data["captured_at_utc"] = "2026-11-02T13:56:00Z"
    data["event_names"] = ["WWT Championship"]
    data["competitive_start"] = {
        "WWT Championship": {"state": "date_only", "competitive_start_date": start}
    }
    template = data["rows"][0]
    data["rows"] = [
        {**template, "event_name": "WWT Championship", "season": "2026",
         "player_name": name, "captured_at_utc": data["captured_at_utc"]}
        for name in (names if names is not None else [f"Player {i}" for i in range(12)])
    ]
    path = tmp_path / "wwt.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _initialism_board(snapshot, **overrides):
    return _annotate(
        _rows(*(f"Player {i}" for i in range(12))),
        event_name="World Wide Technology Championship",
        event_key="world_wide_technology_championship_2026",
        event_date="2026-11-05", odds_snapshot=snapshot, **overrides,
    )


def test_initialism_join_needs_date_and_strong_field_evidence(tmp_path):
    snapshot = _initialism_snapshot(tmp_path, names=[f"Player {i}" for i in range(10)])
    rows, odds = _initialism_board(snapshot)
    assert odds["event_identity"]["match"] == "initialism"
    assert odds["priced_players"] == 10
    assert odds["event_identity_diagnostics"][0]["matched_field_players"] == 10
    assert rows[0]["price"]["provenance"]["event_match"] == "initialism"


@pytest.mark.parametrize("start,names", [
    ("2026-11-12", [f"Player {i}" for i in range(12)]),
    ("", [f"Player {i}" for i in range(12)]),
    ("2026-11-05", [f"Player {i}" for i in range(9)]),
    ("2026-11-05", [f"Other {i}" for i in range(12)]),
])
def test_initialism_does_not_attach_wrong_week_or_insufficient_field(tmp_path, start, names):
    snapshot = _initialism_snapshot(tmp_path, start=start, names=names)
    rows, odds = _initialism_board(snapshot)
    assert odds["status"] == "unpriced"
    assert all(row["price"] is None for row in rows)
    assert odds["observed_provider_events"] == ["WWT Championship"]
    assert odds["event_identity_diagnostics"][0]["accepted"] is False


def test_initialism_recovers_date_from_canonical_weekly_state(tmp_path):
    snapshot = _initialism_snapshot(tmp_path, start="")
    weekly = tmp_path / "weekly"
    event = weekly / "world_wide_technology_championship_2026"
    event.mkdir(parents=True)
    (event / "event_control.json").write_text(json.dumps({
        "event_key": event.name, "event_name": "World Wide Technology Championship",
        "competitive_start_date": "2026-11-05",
    }), encoding="utf-8")
    _, odds = _initialism_board(snapshot, weekly_dir=weekly)
    assert odds["pre_start"] is True
    assert odds["priced_players"] == 12


def test_conflicting_alias_targets_are_not_resolved_by_first_row(tmp_path):
    aliases = tmp_path / "aliases.csv"
    aliases.write_text(
        "sportsbook,provider_event_name,season,canonical_event_key,canonical_event_name\n"
        "Bovada,Mexico Open,2026,vidantaworld_mexico_open_2026,VidantaWorld Mexico Open\n"
        "Bovada,Mexico Open,2026,some_other_open_2026,Some Other Open\n",
        encoding="utf-8",
    )
    _, odds = _annotate(_rows("Player A"), event_name="VidantaWorld Mexico Open",
                        event_key="vidantaworld_mexico_open_2026", event_aliases_path=aliases)
    assert odds["status"] == "unpriced"
    assert odds["event_identity_diagnostics"][0]["candidate_match"] == "ambiguous_alias"
