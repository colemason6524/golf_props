import csv

from golf_props.cli import main
from golf_props.odds import bovada
from golf_props.odds.bovada import collect_bovada_golf_odds, parse_bovada_payload


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
        ]
    )

    assert exit_code == 0
    assert output.exists()
    assert raw_output.exists()
    assert report_output.exists()
